<div align="center">

# 📡 TG Storage

**Infinite file storage powered by Telegram — with a clean REST API, public CDN URLs, and a built-in test UI.**

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-brightgreen?logo=mongodb&logoColor=white)](https://www.mongodb.com/atlas)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-NitinBot001%2FTG--Storage-black?logo=github)](https://github.com/NitinBot001/TG-Storage)

</div>

---

## ✨ What is TG Storage?

TG Storage turns any Telegram channel into a **free, unlimited cloud storage backend**. You upload files through a REST API — they get stored in your Telegram channel — and you get back a **permanent, public CDN URL** to share anywhere.

No S3. No GCS. No storage bills.

### Key features

- 🚀 **REST API** — Upload, download, list, and delete files via HTTP
- 🔗 **Public CDN URLs** — Shareable links with no auth required (`/cdn/your-path`)
- 🏷️ **Custom paths** — Assign vanity paths like `/cdn/images/logo.png` or `/cdn/avatar.jpg`
- 🤖 **Multi-bot pool** — Add multiple bot tokens to spread Telegram rate limits
- 🧠 **MongoDB Atlas** — File metadata stored in the cloud, zero local state
- 🖥️ **Built-in UI** — Drop-in browser interface to test everything at `/`
- ⚡ **Pure httpx** — No telegram library dependencies, raw Bot API calls only

---

## 📁 Project Structure

```
TG-Storage/
├── main.py            # FastAPI app — all routes & lifespan
├── db.py              # MongoDB Atlas async layer (Motor)
├── tg.py              # Telegram Bot API client (pure httpx)
├── server.py          # Uvicorn entry point
├── frontend.html      # Built-in browser test UI
├── requirements.txt   # Python dependencies
├── vercel.json        # Vercel deployment config
├── .env.example       # Environment variable template
└── tokens.txt         # (you create) one bot token per line
```

---

## 🛠️ Setup & Installation

### 1. Clone the repo

```bash
git clone https://github.com/NitinBot001/TG-Storage.git
cd TG-Storage
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create your Telegram bot(s)

1. Open [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the token (looks like `1234567890:AAExampleTokenHere`)
4. Repeat for as many bots as you want (more bots = higher upload throughput)

### 4. Set up your Telegram channel

1. Create a **private channel** in Telegram
2. Add all your bots as **Administrators** with permission to **post messages**
3. Get the channel ID — forward any message from the channel to [@JsonDumpBot](https://t.me/JsonDumpBot) and look for `"chat": { "id": -1001234567890 }`

### 5. Create `tokens.txt`

```
# tokens.txt — one bot token per line, lines starting with # are ignored
1234567890:AAExampleToken1Here
9876543210:AAExampleToken2Here
```

### 6. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
# Telegram
CHANNEL_ID=-1001234567890

# MongoDB Atlas (get from: Atlas → Connect → Drivers → Python)
MONGODB_URI=mongodb+srv://<user>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGO_DB_NAME=tgstorage

# API auth key — clients must send this in X-API-Key header
ADMIN_API_KEY=your-secret-key-here

# Public base URL — used to build CDN links
# Local dev:   http://localhost:8082
# Production:  https://your-vercel-app.vercel.app
BASE_URL=http://localhost:8082
```

### 7. Run the server

```bash
python server.py
```

Server starts at **http://localhost:8082**
Open it in your browser to access the built-in test UI.

---

## 🌐 API Reference

All endpoints except `/` and `/cdn/*` require the header:
```
X-API-Key: your-secret-key-here
```

### `POST /upload` — Upload a file

**Form fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | ✅ | The file to upload (any format) |
| `custom_path` | string | ❌ | Vanity CDN path, e.g. `images/logo.png` |

**Example:**
```bash
# Upload with auto-generated ID
curl -X POST http://localhost:8082/upload \
  -H "X-API-Key: your-key" \
  -F "file=@photo.jpg"

# Upload with custom path
curl -X POST http://localhost:8082/upload \
  -H "X-API-Key: your-key" \
  -F "file=@logo.png" \
  -F "custom_path=brand/logo.png"
```

**Response:**
```json
{
  "file_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "logo.png",
  "mime_type": "image/png",
  "size_bytes": 20480,
  "custom_path": "brand/logo.png",
  "public_url": "http://localhost:8082/cdn/brand/logo.png",
  "cdn_url_by_id": "http://localhost:8082/cdn/550e8400-...",
  "cdn_url_by_path": "http://localhost:8082/cdn/brand/logo.png",
  "uploaded_at": "2025-01-01T12:00:00"
}
```

---

### `GET /cdn/{path}` — Public CDN URL *(no auth)*

Works with both the UUID file_id and any assigned custom path:

```
GET /cdn/550e8400-e29b-41d4-a716-446655440000   ← by file_id
GET /cdn/logo.png                                ← by custom_path
GET /cdn/images/avatar.jpg                       ← by nested custom_path
```

Files are served `inline` — images, PDFs, and videos render directly in the browser.

---

### `GET /file/{file_id}` — Download *(auth required)*

Forces a file download (`Content-Disposition: attachment`).

```bash
curl -H "X-API-Key: your-key" \
     http://localhost:8082/file/550e8400-... \
     -o downloaded.jpg
```

---

### `GET /files` — List all files

```bash
curl -H "X-API-Key: your-key" \
     "http://localhost:8082/files?limit=50&offset=0"
```

**Response:**
```json
{
  "total": 42,
  "limit": 50,
  "offset": 0,
  "files": [
    {
      "file_id": "...",
      "filename": "photo.jpg",
      "mime_type": "image/jpeg",
      "size_bytes": 204800,
      "custom_path": "photos/summer.jpg",
      "public_url": "http://localhost:8082/cdn/photos/summer.jpg",
      "uploaded_at": "2025-01-01T12:00:00"
    }
  ]
}
```

---

### `DELETE /file/{file_id}` — Delete a record

Removes the metadata from MongoDB. The Telegram message remains in the channel.

```bash
curl -X DELETE -H "X-API-Key: your-key" \
     http://localhost:8082/file/550e8400-...
```

---

### `GET /health` — Health check

```bash
curl http://localhost:8082/health
```

```json
{
  "status": "ok",
  "timestamp": "2025-01-01T12:00:00",
  "total_files": 42,
  "base_url": "http://localhost:8082"
}
```

---

## 🚀 Deploy to Vercel

Vercel runs Python serverless functions — perfect for this API.

### Prerequisites

- A [Vercel account](https://vercel.com) (free tier works)
- The repo pushed to GitHub at `https://github.com/NitinBot001/TG-Storage`

---

### Step 1 — Add `tokens.txt` to the repo *(or use env var)*

> ⚠️ **Do not commit real bot tokens to a public repo.**
>
> Instead, encode your tokens as a single environment variable:

On your machine, run:
```bash
# Join tokens with a newline, then base64-encode
python -c "
import base64
tokens = '1234567890:TokenOne\n9876543210:TokenTwo'
print(base64.b64encode(tokens.encode()).decode())
"
```

Copy the output — you'll add it as `TOKENS_B64` in Vercel. Then update `tg.py` to decode it (see Step 4).

---

### Step 2 — Import project in Vercel

1. Go to [vercel.com/new](https://vercel.com/new)
2. Click **"Import Git Repository"**
3. Select `NitinBot001/TG-Storage`
4. Framework preset: **Other**
5. Click **Deploy** (it will fail — that's fine, we need to add env vars first)

---

### Step 3 — Add environment variables

In your Vercel project → **Settings → Environment Variables**, add:

| Name | Value |
|------|-------|
| `CHANNEL_ID` | `-1001234567890` |
| `MONGODB_URI` | `mongodb+srv://...` |
| `MONGO_DB_NAME` | `tgstorage` |
| `ADMIN_API_KEY` | `your-secret-key` |
| `BASE_URL` | `https://your-app.vercel.app` |
| `TOKENS_B64` | *(base64 string from Step 1)* |

---

### Step 4 — Update `tg.py` to read `TOKENS_B64`

Replace the `_tokens_path()` function in `tg.py` with this loader that checks for the env var first:

```python
import base64, tempfile, os

def _get_tokens() -> list[str]:
    """Read tokens from TOKENS_B64 env var (Vercel) or tokens.txt (local)."""
    b64 = os.getenv("TOKENS_B64", "").strip()
    if b64:
        decoded = base64.b64decode(b64).decode("utf-8")
        return [l.strip() for l in decoded.splitlines() if l.strip() and not l.startswith("#")]

    # Fallback to file
    for candidate in [Path(__file__).parent / "tokens.txt", Path(os.getcwd()) / "tokens.txt"]:
        if candidate.exists():
            return [l.strip() for l in candidate.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")]
    raise FileNotFoundError("No tokens found. Set TOKENS_B64 env var or create tokens.txt.")
```

Then in `init_bot_pool()` replace:
```python
raw_tokens = [...]  # the old file-reading block
```
with:
```python
raw_tokens = _get_tokens()
```

---

### Step 5 — The `vercel.json` is already included

```json
{
  "version": 2,
  "builds": [{ "src": "main.py", "use": "@vercel/python" }],
  "routes": [{ "src": "/(.*)", "dest": "main.py" }]
}
```

---

### Step 6 — Redeploy

Push your changes to GitHub:
```bash
git add tg.py
git commit -m "feat: support TOKENS_B64 for Vercel deployment"
git push
```

Vercel auto-deploys on every push. Your API will be live at:
```
https://tg-storage-xxxx.vercel.app
```

Update `BASE_URL` in Vercel env vars to match your actual deployment URL.

---

### ⚠️ Vercel Limitations

| Limitation | Impact |
|------------|--------|
| **10s function timeout** (Hobby plan) | Large file uploads may time out. Upgrade to Pro (60s) or use a VPS. |
| **4.5 MB request body limit** | Files larger than 4.5 MB cannot be uploaded via Vercel's edge. Use a VPS for large files. |
| **Serverless = stateless** | The bot pool reinitializes on every cold start. `tokens.txt` won't persist — use `TOKENS_B64`. |
| **No persistent filesystem** | MongoDB Atlas handles all state — this is fine. |

For large files or heavy usage, deploy on a **VPS (Railway, Render, DigitalOcean)** instead — run `python server.py` directly with no changes needed.

---

## 🐳 Self-host with Docker *(optional)*

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8082
CMD ["python", "server.py"]
```

```bash
docker build -t tg-storage .
docker run -p 8082:8082 --env-file .env -v $(pwd)/tokens.txt:/app/tokens.txt tg-storage
```

---

## 🔒 Security Notes

- Never expose `ADMIN_API_KEY` publicly — it controls all file operations
- The `/cdn/*` endpoint is intentionally public — anyone with the URL can access the file
- Bot tokens in `tokens.txt` should never be committed to a public repo
- MongoDB URI contains credentials — keep it in `.env` / Vercel environment variables only

---

## 📜 License

MIT — free to use, modify, and deploy.

---

<div align="center">
Built with ❤️ using FastAPI + Telegram Bot API + MongoDB Atlas
<br/>
<a href="https://github.com/NitinBot001/TG-Storage">⭐ Star on GitHub</a>
</div>