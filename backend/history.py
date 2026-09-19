"""Persistent fix request history — survives container restarts."""

import json
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "history.json"

_history: list[dict] = []


def _load():
    global _history
    if HISTORY_FILE.exists():
        try:
            _history = json.loads(HISTORY_FILE.read_text())
        except Exception:
            _history = []


def _save():
    HISTORY_FILE.write_text(json.dumps(_history, indent=2))


_load()


def record(user_id: int, username: str, media_type: str, title: str, episode_id: int = 0, movie_id: int = 0):
    _history.append({
        "userId": user_id,
        "username": username,
        "type": media_type,
        "title": title,
        "episodeId": episode_id,
        "movieId": movie_id,
        "timestamp": time.time(),
    })
    # Keep last 500
    if len(_history) > 500:
        _history[:] = _history[-500:]
    _save()


def get_all(limit: int = 100) -> list[dict]:
    return list(reversed(_history[-limit:]))


def get_for_user(user_id: int, limit: int = 50) -> list[dict]:
    user_items = [h for h in _history if h["userId"] == user_id]
    return list(reversed(user_items[-limit:]))


def was_fixed_today(user_id: int, media_type: str, episode_id: int = 0, movie_id: int = 0) -> bool:
    from datetime import datetime
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    for entry in _history:
        if entry["userId"] != user_id or entry["timestamp"] < today_start:
            continue
        if media_type == "episode" and entry.get("episodeId") == episode_id:
            return True
        if media_type == "movie" and entry.get("movieId") == movie_id:
            return True
    return False
