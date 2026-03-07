"""
server.py — Entry point. Loads .env then starts Flask.

Run:
    python server.py
"""

from dotenv import load_dotenv

load_dotenv()  # load .env before importing app so env vars are available

from main import app

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8082,
        debug=True,
    )