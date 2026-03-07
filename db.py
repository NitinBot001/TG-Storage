"""
db.py — Async MongoDB Atlas metadata store using Motor.
Collection: tgstorage.files
"""

import os
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import DESCENDING

MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("MONGO_DB_NAME", "tgstorage")

_client: Optional[AsyncIOMotorClient] = None


def _get_collection():
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URI)
    return _client[DB_NAME]["files"]


async def init_db():
    """Ensure indexes exist."""
    col = _get_collection()
    await col.create_index("file_id", unique=True)
    await col.create_index([("uploaded_at", DESCENDING)])
    # sparse=True so documents without custom_path don't conflict
    await col.create_index("custom_path", unique=True, sparse=True)


# ──────────────────────────────────────────────────
#  CRUD
# ──────────────────────────────────────────────────

async def save_file_record(
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
    col = _get_collection()
    doc = {
        "file_id":       file_id,
        "filename":      filename,
        "mime_type":     mime_type,
        "size_bytes":    size,
        "tg_message_id": tg_message_id,
        "tg_file_id":    tg_file_id,
        "public_url":    public_url,
        "uploaded_at":   datetime.utcnow().isoformat(),
    }
    if custom_path:
        doc["custom_path"] = custom_path
    await col.insert_one(doc)


async def get_file_record(file_id: str) -> dict | None:
    col = _get_collection()
    return await col.find_one({"file_id": file_id}, {"_id": 0})


async def get_file_by_custom_path(custom_path: str) -> dict | None:
    col = _get_collection()
    return await col.find_one({"custom_path": custom_path}, {"_id": 0})


async def list_file_records(limit: int = 50, offset: int = 0) -> list[dict]:
    col = _get_collection()
    cursor = (
        col.find({}, {"_id": 0})
           .sort("uploaded_at", DESCENDING)
           .skip(offset)
           .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def delete_file_record(file_id: str):
    col = _get_collection()
    await col.delete_one({"file_id": file_id})


async def count_files() -> int:
    col = _get_collection()
    return await col.count_documents({})