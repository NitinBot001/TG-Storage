# TG Storage API

Infinite file storage powered by Telegram — wrap it in a clean REST API.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in API_ID, API_HASH, CHANNEL_ID, ADMIN_API_KEY

# 3. Add bot tokens (one per line)
echo "1234567890:AAEXAMPLE..." >> tokens.txt

# 4. Start the server
python server.py
# → http://localhost:8082
```

---

## Endpoints

All endpoints require the header:
```
X-API-Key: <your ADMIN_API_KEY>
```

### Upload a file
```
POST /upload
Content-Type: multipart/form-data

file=@/path/to/yourfile.pdf
```
**Response:**
```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "yourfile.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 102400,
  "uploaded_at": "2025-01-01T12:00:00"
}
```

---

### Download a file
```
GET /file/{file_id}
```
Streams the file with the original filename and content-type.

**cURL example:**
```bash
curl -H "X-API-Key: your-key" \
     http://localhost:8082/file/550e8400-... \
     -o downloaded_file.pdf
```

---

### List all files
```
GET /files?limit=50&offset=0
```
**Response:**
```json
{
  "total": 3,
  "limit": 50,
  "offset": 0,
  "files": [
    {
      "file_id": "...",
      "filename": "photo.jpg",
      "mime_type": "image/jpeg",
      "size_bytes": 204800,
      "uploaded_at": "2025-01-01T12:00:00"
    }
  ]
}
```

---

### Delete a file record
```
DELETE /file/{file_id}
```
Removes the metadata record (the Telegram message remains in the channel).

---

### Health check
```
GET /health
```

---

## Python Client Example

```python
import httpx

BASE = "http://localhost:8082"
HEADERS = {"X-API-Key": "super-secret-key-change-me"}

# Upload
with open("photo.jpg", "rb") as f:
    r = httpx.post(f"{BASE}/upload", headers=HEADERS, files={"file": f})
file_id = r.json()["file_id"]
print("Uploaded:", file_id)

# Download
r = httpx.get(f"{BASE}/file/{file_id}", headers=HEADERS)
with open("downloaded.jpg", "wb") as f:
    f.write(r.content)
print("Downloaded!")

# List
r = httpx.get(f"{BASE}/files", headers=HEADERS)
print(r.json())
```

---

## Project Structure
```
tg_storage_api/
├── main.py          # FastAPI app & routes
├── db.py            # SQLite metadata layer (aiosqlite)
├── tg.py            # Telegram upload/download via tgstorage-cluster
├── server.py        # Uvicorn entry point
├── requirements.txt
├── .env.example
└── tokens.txt       # (you create) one bot token per line
```

## Interactive Docs
Visit `http://localhost:8082/docs` for the full Swagger UI.
