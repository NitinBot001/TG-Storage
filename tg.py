"""
tg.py — Pure-HTTP Telegram Bot API client. No tgstorage-cluster, no
        python-telegram-bot. Just httpx + the official Bot API.

Bot pool:
  • Reads tokens.txt (one token per line) at startup via init_bot_pool().
  • Verifies each token with getMe(). Skips bad/dead tokens.
  • Round-robins uploads across all healthy bots to spread rate-limit load.

Upload flow:
  sendDocument  →  returns message_id + file_id  →  stored in MongoDB.

Download flow (two-stage):
  1. getFile(file_id)          →  get a temporary download path from Telegram.
  2. GET https://api.telegram.org/file/bot{token}/{file_path}  →  raw bytes.
  File paths expire after ~1 h, so we always call getFile fresh.
"""

import os
import io
import itertools
import logging
from pathlib import Path
from typing import Tuple

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────────────
TG_API  = "https://api.telegram.org/bot{token}/{method}"
TG_FILE = "https://api.telegram.org/file/bot{token}/{file_path}"

# Telegram hard limit for getFile downloads via Bot API is 20 MB.
# Files larger than this must be sent as separate parts (chunking) or
# via a Telegram client (MTProto). We warn but still attempt.
TG_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)


# ──────────────────────────────────────────────────────────────────────
#  Shared async HTTP client (one per process)
# ──────────────────────────────────────────────────────────────────────
_http: httpx.AsyncClient | None = None

def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)
    return _http


async def close_http():
    """Call on app shutdown to cleanly drain the connection pool."""
    global _http
    if _http and not _http.is_closed:
        await _http.aclose()
        _http = None


# ──────────────────────────────────────────────────────────────────────
#  Bot pool
# ──────────────────────────────────────────────────────────────────────
_pool:  list[dict] = []   # [{"token": str, "username": str, "id": int}, …]
_cycle: itertools.cycle | None = None


def _tokens_path() -> Path:
    """Look for tokens.txt next to this file, then in cwd."""
    for candidate in [Path(__file__).parent / "tokens.txt",
                      Path(os.getcwd()) / "tokens.txt"]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "tokens.txt not found. Create it with one bot token per line.\n"
        "Example:  123456789:AAExampleTokenHere"
    )


async def _verify_token(token: str) -> dict | None:
    """Call getMe to validate a token. Returns bot info dict or None."""
    url = TG_API.format(token=token, method="getMe")
    try:
        r = await _client().get(url)
        data = r.json()
        if data.get("ok"):
            bot = data["result"]
            return {"token": token, "username": bot["username"], "id": bot["id"]}
        logger.warning(f"✗ Token rejected by Telegram ({token[:20]}…): {data.get('description')}")
    except Exception as e:
        logger.warning(f"✗ Could not reach Telegram for token {token[:20]}…: {e}")
    return None


async def init_bot_pool():
    """
    Read tokens.txt, verify each token with getMe(), build the round-robin pool.
    Raises RuntimeError if no healthy bots are found.
    """
    global _pool, _cycle

    path = _tokens_path()
    raw_tokens = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    if not raw_tokens:
        raise RuntimeError(f"tokens.txt at {path} is empty — add at least one bot token.")

    healthy = []
    for token in raw_tokens:
        info = await _verify_token(token)
        if info:
            logger.info(f"✓ Bot ready: @{info['username']} (id={info['id']})")
            healthy.append(info)

    if not healthy:
        raise RuntimeError(
            "No healthy bots found.\n"
            "• Check tokens.txt — each line must be a valid BotFather token.\n"
            "• The bot must be added as an Administrator to your CHANNEL_ID."
        )

    _pool  = healthy
    _cycle = itertools.cycle(_pool)
    logger.info(f"Bot pool ready — {len(_pool)} bot(s) active.")


def _next_bot() -> dict:
    if not _pool:
        raise RuntimeError(
            "Bot pool is empty. Make sure init_bot_pool() ran at startup "
            "and tokens.txt contains at least one valid token."
        )
    return next(_cycle)  # type: ignore[arg-type]


def _get_channel_id() -> int:
    raw = os.getenv("CHANNEL_ID", "0").strip()
    if not raw or raw == "0":
        raise RuntimeError(
            "CHANNEL_ID is not set.\n"
            "Add to .env:  CHANNEL_ID=-1001234567890\n"
            "Tip: forward any message from the channel to @JsonDumpBot to get the ID."
        )
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"CHANNEL_ID must be an integer, got: {raw!r}")


# ──────────────────────────────────────────────────────────────────────
#  Low-level API helpers
# ──────────────────────────────────────────────────────────────────────

async def _api(token: str, method: str, **kwargs) -> dict:
    """
    POST to a Bot API method with JSON body.
    Raises RuntimeError on non-ok responses.
    """
    url = TG_API.format(token=token, method=method)
    r = await _client().post(url, **kwargs)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(
            f"Telegram API error on {method}: "
            f"[{data.get('error_code')}] {data.get('description')}"
        )
    return data["result"]


# ──────────────────────────────────────────────────────────────────────
#  Upload
# ──────────────────────────────────────────────────────────────────────

async def upload_to_telegram(
    content: bytes,
    filename: str,
    mime_type: str,
) -> Tuple[int, str]:
    """
    Upload raw bytes to the Telegram channel as a document.
    Returns: (message_id, tg_file_id)
    """
    channel_id = _get_channel_id()
    bot = _next_bot()

    files   = {"document": (filename, io.BytesIO(content), mime_type)}
    payload = {
        "chat_id": channel_id,
        "caption": f"📁 {filename}  •  {mime_type}  •  {len(content):,} B",
    }

    try:
        msg = await _api(
            bot["token"], "sendDocument",
            data=payload,
            files=files,
        )
    except RuntimeError as e:
        raise RuntimeError(
            f"{e}\n"
            f"Bot: @{bot['username']}  |  Channel: {channel_id}\n"
            f"Make sure the bot is an Administrator in the channel."
        )

    doc        = msg["document"]
    file_id    = doc["file_id"]
    message_id = msg["message_id"]

    logger.info(f"Uploaded {filename!r} → msg_id={message_id}  file_id={file_id[:24]}…")
    return message_id, file_id


# ──────────────────────────────────────────────────────────────────────
#  Download
# ──────────────────────────────────────────────────────────────────────

async def download_from_telegram(
    tg_message_id: int,
    tg_file_id: str | None,
) -> bytes:
    """
    Download and return the raw bytes of a stored file.

    Strategy:
      1. Call getFile(file_id) to resolve the temporary download path.
      2. GET the file bytes from the CDN path.
      3. If step 1 fails (file_id stale), fall back to forwarding the
         original message and re-extracting the document's file_id.
    """
    channel_id = _get_channel_id()
    bot        = _next_bot()

    # ── Stage 1: resolve download path ──────────────────────────────
    file_path: str | None = None

    if tg_file_id:
        try:
            result    = await _api(bot["token"], "getFile", json={"file_id": tg_file_id})
            file_path = result.get("file_path")
        except RuntimeError as e:
            logger.warning(f"getFile failed for file_id {tg_file_id[:24]}…, trying message fallback. ({e})")

    # ── Stage 2: message fallback if file_id is stale ───────────────
    if not file_path:
        try:
            fwd = await _api(bot["token"], "forwardMessage", json={
                "chat_id":      channel_id,
                "from_chat_id": channel_id,
                "message_id":   tg_message_id,
            })
        except RuntimeError as e:
            raise RuntimeError(
                f"Could not retrieve message {tg_message_id} from channel {channel_id}.\n"
                f"Ensure the bot can read the channel. Detail: {e}"
            )

        doc = fwd.get("document")
        if not doc:
            raise ValueError(f"Message {tg_message_id} contains no document.")

        result    = await _api(bot["token"], "getFile", json={"file_id": doc["file_id"]})
        file_path = result.get("file_path")

    if not file_path:
        raise RuntimeError("Telegram did not return a file_path — file may be too large for Bot API (>20 MB).")

    # ── Stage 3: download bytes ──────────────────────────────────────
    url = TG_FILE.format(token=bot["token"], file_path=file_path)
    r   = await _client().get(url)

    if r.status_code != 200:
        raise RuntimeError(f"File download failed: HTTP {r.status_code} from Telegram CDN.")

    logger.info(f"Downloaded {len(r.content):,} bytes for msg_id={tg_message_id}")
    return r.content