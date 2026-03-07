"""
server.py — Entry point. Loads .env then starts Uvicorn.

Run:
    python server.py
or directly:
    uvicorn main:app --host 0.0.0.0 --port 8082
"""

import sys
import uvicorn
from dotenv import load_dotenv

load_dotenv()  # load .env before importing app so env vars are available

if __name__ == "__main__":
    # reload=True causes a multiprocessing crash on Python 3.13 + Windows.
    # Use reload only on Python < 3.13, otherwise run without it.
    py313_or_above = sys.version_info >= (3, 13)

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8082,
        reload=not py313_or_above,   # disabled on 3.13+ Windows to avoid BufferFlags crash
        log_level="info",
    )