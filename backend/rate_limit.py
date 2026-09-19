import json
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CONFIG_FILE = DATA_DIR / "rate_config.json"
REQUESTS_FILE = DATA_DIR / "rate_requests.json"

DEFAULT_MAX_PER_DAY = 10
DEFAULT_COOLDOWN = 60  # 1 minute

# user_id -> list of timestamps
_requests: dict[int, list[float]] = {}

# user_id -> {maxPerDay, cooldown} overrides
_user_config: dict[int, dict] = {}


def _load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            _user_config.clear()
            for uid_str, cfg in data.items():
                _user_config[int(uid_str)] = cfg
        except Exception:
            pass


def _save_config():
    CONFIG_FILE.write_text(json.dumps(
        {str(uid): cfg for uid, cfg in _user_config.items()},
        indent=2,
    ))


def _load_requests():
    if REQUESTS_FILE.exists():
        try:
            data = json.loads(REQUESTS_FILE.read_text())
            _requests.clear()
            cutoff = _today_start()
            for uid_str, timestamps in data.items():
                valid = [t for t in timestamps if t >= cutoff]
                if valid:
                    _requests[int(uid_str)] = valid
        except Exception:
            pass


def _save_requests():
    REQUESTS_FILE.write_text(json.dumps(
        {str(uid): ts for uid, ts in _requests.items()},
        indent=2,
    ))


_load_config()
_load_requests()


def get_user_limits(user_id: int) -> tuple[int, int]:
    cfg = _user_config.get(user_id, {})
    return (
        cfg.get("maxPerDay", DEFAULT_MAX_PER_DAY),
        cfg.get("cooldown", DEFAULT_COOLDOWN),
    )


def set_user_limits(user_id: int, max_per_day: int, cooldown: int):
    _user_config[user_id] = {"maxPerDay": max_per_day, "cooldown": cooldown}
    _save_config()


def _today_start() -> float:
    now = datetime.now()
    return datetime(now.year, now.month, now.day).timestamp()


def _clean(user_id: int):
    cutoff = _today_start()
    _requests[user_id] = [t for t in _requests.get(user_id, []) if t >= cutoff]


def check_rate_limit(user_id: int) -> str | None:
    _clean(user_id)
    max_per_day, cooldown = get_user_limits(user_id)
    timestamps = _requests.get(user_id, [])

    if len(timestamps) >= max_per_day:
        return f"Daily limit reached ({max_per_day} fixes per day)"

    if timestamps:
        last = timestamps[-1]
        elapsed = time.time() - last
        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            return f"Cooldown active — wait {remaining}s"

    return None


def record_request(user_id: int):
    _clean(user_id)
    _requests.setdefault(user_id, []).append(time.time())
    _save_requests()


def get_rate_info(user_id: int) -> dict:
    _clean(user_id)
    max_per_day, cooldown = get_user_limits(user_id)
    timestamps = _requests.get(user_id, [])
    remaining = max_per_day - len(timestamps)
    cooldown_left = 0
    if timestamps:
        elapsed = time.time() - timestamps[-1]
        if elapsed < cooldown:
            cooldown_left = int(cooldown - elapsed)
    return {
        "remaining": max(0, remaining),
        "maxPerDay": max_per_day,
        "cooldown": cooldown,
        "cooldownLeft": cooldown_left,
    }
