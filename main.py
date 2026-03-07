"""
TG Storage API — Store & retrieve files via Telegram as a backend.

Endpoints:
  GET    /                        — Frontend UI
  POST   /upload                  — Upload a file (optional custom_path)
  GET    /cdn/<path>              — Public CDN URL — works with:
                                      /cdn/<file_id>
                                      /cdn/<custom_path>        e.g. /cdn/logo.png
                                      /cdn/<folder/name.ext>   e.g. /cdn/images/avatar.jpg
  GET    /file/<file_id>          — Download (auth required, forces attachment)
  GET    /files                   — List all stored files
  DELETE /file/<file_id>          — Delete a file record
  GET    /health                  — Health check
"""

import os
import re
import uuid
import logging
import mimetypes
import atexit
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from flask import Flask, request, jsonify, Response, abort, send_file
from flask_cors import CORS

from db import (
    init_db, save_file_record,
    get_file_record, get_file_by_custom_path,
    list_file_records, delete_file_record, count_files,
)
from tg import upload_to_telegram, download_from_telegram, init_bot_pool, close_http

# ──────────────────────────────────────────────────
#  App
# ──────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "changeme")
BASE_URL      = os.getenv("BASE_URL", "http://localhost:8082").rstrip("/")

_HERE         = Path(__file__).parent
FRONTEND_PATH = _HERE / "frontend.html"

# Allowed characters in a custom path segment
_CUSTOM_PATH_RE = re.compile(r'^[a-zA-Z0-9._\-/]+$')

# ──────────────────────────────────────────────────
#  Startup / Shutdown
# ──────────────────────────────────────────────────
_initialized = False

def _startup():
    global _initialized
    if _initialized:
        return
    init_db()          # connect Supabase + verify table exists
    init_bot_pool()    # verify tokens.txt & build bot pool
    _initialized = True

atexit.register(close_http)  # drain httpx connection pool on exit


# ──────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────
def require_api_key():
    key = request.headers.get("X-API-Key", "")
    if key != ADMIN_API_KEY:
        abort(401, description="Invalid or missing API key")


def _sanitize_custom_path(raw: str) -> str:
    path = raw.strip().strip("/")
    if not path:
        abort(400, description="custom_path cannot be empty after stripping slashes.")
    if ".." in path:
        abort(400, description="custom_path must not contain '..'")
    if not _CUSTOM_PATH_RE.match(path):
        abort(400, description="custom_path may only contain letters, digits, hyphens, underscores, dots, and slashes.")
    return path


def _build_public_url(identifier: str) -> str:
    return f"{BASE_URL}/cdn/{identifier}"


def _make_stream_response(record: dict, disposition: str = "inline") -> Response:
    """Download from Telegram and return to client."""
    try:
        data: bytes = download_from_telegram(record["tg_message_id"], record["tg_file_id"])
    except Exception as exc:
        logger.exception("Telegram download error")
        abort(502, description=str(exc))

    return Response(
        data,
        mimetype=record["mime_type"],
        headers={
            "Content-Disposition": f'{disposition}; filename="{record["filename"]}"',
            "Content-Length":      str(len(data)),
            "Cache-Control":       "public, max-age=31536000, immutable",
        },
    )


# ──────────────────────────────────────────────────
#  Routes
# ──────────────────────────────────────────────────

@app.route("/")
def frontend():
    if FRONTEND_PATH.exists():
        return Response(FRONTEND_PATH.read_text(encoding="utf-8"), mimetype="text/html")
    return Response("<h2>frontend.html not found</h2>", status=404, mimetype="text/html")


@app.route("/health")
def health():
    _startup()
    total = count_files()
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_files": total,
        "base_url": BASE_URL,
    })


# ── CDN — public, no auth ─────────────────────────────────────────────
@app.route("/cdn/<path:path>")
def cdn_file(path: str):
    _startup()
    # 1 — custom path lookup
    record = get_file_by_custom_path(path)

    # 2 — fall back to file_id lookup
    if not record:
        record = get_file_record(path)

    if not record:
        return jsonify({
            "detail": f"No file found for path '{path}'. "
                      f"Provide a valid file_id or a custom_path assigned at upload."
        }), 404

    return _make_stream_response(record)


# ── Upload ────────────────────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
def upload_file_route():
    _startup()
    require_api_key()

    if "file" not in request.files:
        return jsonify({"detail": "No file provided."}), 400

    file = request.files["file"]
    content = file.read()
    if not content:
        return jsonify({"detail": "Empty file."}), 400

    filename  = file.filename or f"upload_{uuid.uuid4().hex}"
    mime_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    size      = len(content)

    # Validate + normalise custom_path if provided
    clean_custom_path = None
    custom_path_raw = request.form.get("custom_path", "")
    if custom_path_raw and custom_path_raw.strip():
        clean_custom_path = _sanitize_custom_path(custom_path_raw)
        existing = get_file_by_custom_path(clean_custom_path)
        if existing:
            return jsonify({
                "detail": f"custom_path '{clean_custom_path}' is already taken by file_id={existing['file_id']}."
            }), 409

    # Upload bytes to Telegram
    try:
        tg_message_id, tg_file_id = upload_to_telegram(content, filename, mime_type)
    except Exception as exc:
        logger.exception("Telegram upload error")
        return jsonify({"detail": str(exc)}), 502

    # Build URLs
    file_id    = str(uuid.uuid4())
    cdn_key    = clean_custom_path if clean_custom_path else file_id
    public_url = _build_public_url(cdn_key)

    save_file_record(
        file_id=file_id,
        filename=filename,
        mime_type=mime_type,
        size=size,
        tg_message_id=tg_message_id,
        tg_file_id=tg_file_id,
        public_url=public_url,
        custom_path=clean_custom_path,
    )

    logger.info(f"Uploaded {filename!r} → {public_url}")

    return jsonify({
        "file_id":     file_id,
        "filename":    filename,
        "mime_type":   mime_type,
        "size_bytes":  size,
        "custom_path": clean_custom_path,
        "public_url":  public_url,
        "cdn_url_by_id":   _build_public_url(file_id),
        "cdn_url_by_path": _build_public_url(clean_custom_path) if clean_custom_path else None,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    })


# ── Authenticated download ────────────────────────────────────────────
@app.route("/file/<file_id>", methods=["GET"])
def download_file_route(file_id: str):
    _startup()
    require_api_key()

    record = get_file_record(file_id)
    if not record:
        return jsonify({"detail": "File not found."}), 404

    try:
        data: bytes = download_from_telegram(record["tg_message_id"], record["tg_file_id"])
    except Exception as exc:
        logger.exception("Download error")
        return jsonify({"detail": str(exc)}), 502

    return Response(
        data,
        mimetype=record["mime_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{record["filename"]}"',
            "Content-Length":      str(len(data)),
        },
    )


# ── List ──────────────────────────────────────────────────────────────
@app.route("/files")
def list_files_route():
    _startup()
    require_api_key()

    limit  = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit  = max(1, min(limit, 500))
    offset = max(0, offset)

    records = list_file_records(limit=limit, offset=offset)
    total   = count_files()
    return jsonify({"total": total, "limit": limit, "offset": offset, "files": records})


# ── Delete ────────────────────────────────────────────────────────────
@app.route("/file/<file_id>", methods=["DELETE"])
def delete_file_route(file_id: str):
    _startup()
    require_api_key()

    record = get_file_record(file_id)
    if not record:
        return jsonify({"detail": "File not found."}), 404
    delete_file_record(file_id)
    return jsonify({"deleted": True, "file_id": file_id})