"""
TG Storage API — Store & retrieve files via Telegram as a backend.

Endpoints:
  GET    /                        — Frontend UI
  POST   /upload                  — Upload a file (optional custom_path)
  GET    /cdn/{path}              — Public CDN URL — works with:
                                      /cdn/<file_id>
                                      /cdn/<custom_path>        e.g. /cdn/logo.png
                                      /cdn/<folder/name.ext>   e.g. /cdn/images/avatar.jpg
  GET    /file/{file_id}          — Download (auth required, forces attachment)
  GET    /files                   — List all stored files
  DELETE /file/{file_id}          — Delete a file record
  GET    /health                  — Health check
"""

import os
import io
import re
import uuid
import logging
import mimetypes
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from db import (
    init_db, save_file_record,
    get_file_record, get_file_by_custom_path,
    list_file_records, delete_file_record, count_files,
)
from tg import upload_to_telegram, download_from_telegram, init_bot_pool, close_http

# ──────────────────────────────────────────────────
#  Lifespan
# ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()        # connect MongoDB Atlas + ensure indexes
    await init_bot_pool()  # verify tokens.txt & build bot pool
    yield
    await close_http()     # drain httpx connection pool

# ──────────────────────────────────────────────────
#  App
# ──────────────────────────────────────────────────
app = FastAPI(
    title="TG Storage API",
    description="Infinite file storage powered by Telegram",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "changeme")
BASE_URL      = os.getenv("BASE_URL", "http://localhost:8082").rstrip("/")

_HERE         = Path(__file__).parent
FRONTEND_PATH = _HERE / "frontend.html"

# Allowed characters in a custom path segment:
# alphanumeric, hyphen, underscore, dot, forward slash
_CUSTOM_PATH_RE = re.compile(r'^[a-zA-Z0-9._\-/]+$')


# ──────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────
async def require_api_key(x_api_key: str = Header(..., description="Your API key")):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


def _sanitize_custom_path(raw: str) -> str:
    """
    Normalise and validate a custom path.
    - Strip leading/trailing slashes and whitespace
    - Reject empty, path-traversal attempts, or illegal characters
    """
    path = raw.strip().strip("/")
    if not path:
        raise HTTPException(status_code=400, detail="custom_path cannot be empty after stripping slashes.")
    if ".." in path:
        raise HTTPException(status_code=400, detail="custom_path must not contain '..'")
    if not _CUSTOM_PATH_RE.match(path):
        raise HTTPException(
            status_code=400,
            detail="custom_path may only contain letters, digits, hyphens, underscores, dots, and slashes."
        )
    return path


def _build_public_url(identifier: str) -> str:
    """identifier is either a file_id UUID or a normalised custom_path."""
    return f"{BASE_URL}/cdn/{identifier}"


async def _stream_record(record: dict) -> StreamingResponse:
    """Download from Telegram and stream to client."""
    try:
        data: bytes = await download_from_telegram(record["tg_message_id"], record["tg_file_id"])
    except Exception as exc:
        logger.exception("Telegram download error")
        raise HTTPException(status_code=502, detail=str(exc))

    return StreamingResponse(
        io.BytesIO(data),
        media_type=record["mime_type"],
        headers={
            "Content-Disposition": f'inline; filename="{record["filename"]}"',
            "Content-Length":      str(len(data)),
            "Cache-Control":       "public, max-age=31536000, immutable",
        },
    )


# ──────────────────────────────────────────────────
#  Routes
# ──────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def frontend():
    if FRONTEND_PATH.exists():
        return HTMLResponse(FRONTEND_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>frontend.html not found</h2>", status_code=404)


@app.get("/health", tags=["System"])
async def health():
    total = await count_files()
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat(),
            "total_files": total, "base_url": BASE_URL}


# ── CDN — public, no auth ─────────────────────────────────────────────
@app.get(
    "/cdn/{path:path}",
    tags=["CDN"],
    summary="Public shareable URL — supports UUID file_id or any custom path",
)
async def cdn_file(path: str):
    """
    Resolve priority:
      1. Exact match on custom_path  (e.g. /cdn/images/logo.png)
      2. Exact match on file_id UUID (e.g. /cdn/550e8400-...)
    """
    # 1 — custom path lookup
    record = await get_file_by_custom_path(path)

    # 2 — fall back to file_id lookup
    if not record:
        record = await get_file_record(path)

    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No file found for path '{path}'. "
                   f"Provide a valid file_id or a custom_path assigned at upload."
        )

    return await _stream_record(record)


# ── Upload ────────────────────────────────────────────────────────────
@app.post(
    "/upload",
    tags=["Files"],
    summary="Upload a file. Optionally assign a custom CDN path.",
)
async def upload_file(
    file: UploadFile = File(...),
    custom_path: Optional[str] = Form(
        default=None,
        description=(
            "Optional vanity path for the CDN URL. "
            "Examples: 'logo.png', 'images/avatar.jpg', 'docs/readme.md'. "
            "Must be unique. Leave blank to use the auto-generated file_id."
        ),
    ),
    _: str = Depends(require_api_key),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    filename  = file.filename or f"upload_{uuid.uuid4().hex}"
    mime_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    size      = len(content)

    # Validate + normalise custom_path if provided
    clean_custom_path: str | None = None
    if custom_path and custom_path.strip():
        clean_custom_path = _sanitize_custom_path(custom_path)
        # Check uniqueness before hitting Telegram
        existing = await get_file_by_custom_path(clean_custom_path)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"custom_path '{clean_custom_path}' is already taken by file_id={existing['file_id']}."
            )

    # Upload bytes to Telegram
    try:
        tg_message_id, tg_file_id = await upload_to_telegram(content, filename, mime_type)
    except Exception as exc:
        logger.exception("Telegram upload error")
        raise HTTPException(status_code=502, detail=str(exc))

    # Build URLs
    file_id    = str(uuid.uuid4())
    cdn_key    = clean_custom_path if clean_custom_path else file_id
    public_url = _build_public_url(cdn_key)

    await save_file_record(
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

    return {
        "file_id":     file_id,
        "filename":    filename,
        "mime_type":   mime_type,
        "size_bytes":  size,
        "custom_path": clean_custom_path,
        "public_url":  public_url,
        "cdn_url_by_id":   _build_public_url(file_id),
        "cdn_url_by_path": _build_public_url(clean_custom_path) if clean_custom_path else None,
        "uploaded_at": datetime.utcnow().isoformat(),
    }


# ── Authenticated download ────────────────────────────────────────────
@app.get("/file/{file_id}", tags=["Files"], summary="Download (auth required, forces attachment)")
async def download_file(file_id: str, _: str = Depends(require_api_key)):
    record = await get_file_record(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")

    try:
        data: bytes = await download_from_telegram(record["tg_message_id"], record["tg_file_id"])
    except Exception as exc:
        logger.exception("Download error")
        raise HTTPException(status_code=502, detail=str(exc))

    return StreamingResponse(
        io.BytesIO(data),
        media_type=record["mime_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{record["filename"]}"',
            "Content-Length":      str(len(data)),
        },
    )


# ── List ──────────────────────────────────────────────────────────────
@app.get("/files", tags=["Files"], summary="List all stored files")
async def list_files(
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: str = Depends(require_api_key),
):
    records = await list_file_records(limit=limit, offset=offset)
    total   = await count_files()
    return {"total": total, "limit": limit, "offset": offset, "files": records}


# ── Delete ────────────────────────────────────────────────────────────
@app.delete("/file/{file_id}", tags=["Files"], summary="Delete a file record")
async def delete_file(file_id: str, _: str = Depends(require_api_key)):
    record = await get_file_record(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")
    await delete_file_record(file_id)
    return {"deleted": True, "file_id": file_id}