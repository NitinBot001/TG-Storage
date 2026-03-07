"""
db.py — Supabase (PostgreSQL) metadata store.
Table: files

Before first run, create the table in Supabase SQL Editor:

    CREATE TABLE IF NOT EXISTS files (
        id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
        file_id     TEXT UNIQUE NOT NULL,
        filename    TEXT NOT NULL,
        mime_type   TEXT NOT NULL,
        size_bytes  BIGINT NOT NULL,
        tg_message_id BIGINT NOT NULL,
        tg_file_id  TEXT,
        public_url  TEXT NOT NULL,
        custom_path TEXT UNIQUE,
        uploaded_at TIMESTAMPTZ DEFAULT now()
    );
"""

import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_supabase: Optional[Client] = None

TABLE = "files"


def _get_client() -> Client:
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment / .env"
            )
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def init_db():
    """Verify Supabase connection by performing a lightweight query."""
    client = _get_client()
    client.table(TABLE).select("file_id").limit(1).execute()


# ──────────────────────────────────────────────────
#  CRUD
# ──────────────────────────────────────────────────

def save_file_record(
    *,
    file_id: str,
    filename: str,
    mime_type: str,
    size: int,
    tg_message_id: int,
    tg_file_id: str | None,
    public_url: str,
    custom_path: str | None = None,
):
    client = _get_client()
    row = {
        "file_id":       file_id,
        "filename":      filename,
        "mime_type":     mime_type,
        "size_bytes":    size,
        "tg_message_id": tg_message_id,
        "tg_file_id":    tg_file_id,
        "public_url":    public_url,
        "uploaded_at":   datetime.now(timezone.utc).isoformat(),
    }
    if custom_path:
        row["custom_path"] = custom_path
    client.table(TABLE).insert(row).execute()


def get_file_record(file_id: str) -> dict | None:
    client = _get_client()
    resp = (
        client.table(TABLE)
        .select("*")
        .eq("file_id", file_id)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0]
    return None


def get_file_by_custom_path(custom_path: str) -> dict | None:
    client = _get_client()
    resp = (
        client.table(TABLE)
        .select("*")
        .eq("custom_path", custom_path)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0]
    return None


def list_file_records(limit: int = 50, offset: int = 0) -> list[dict]:
    client = _get_client()
    resp = (
        client.table(TABLE)
        .select("*")
        .order("uploaded_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []


def delete_file_record(file_id: str):
    client = _get_client()
    client.table(TABLE).delete().eq("file_id", file_id).execute()


def count_files() -> int:
    client = _get_client()
    resp = (
        client.table(TABLE)
        .select("file_id", count="exact")
        .execute()
    )
    return resp.count or 0