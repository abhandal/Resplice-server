"""Apple Push Notification service sender.

Token-based auth (a .p8 key from the Apple developer portal), which is the
modern path — no certificates to renew. Three identifiers name the key and the
account, and the key itself is the only secret:

    APNS_KEY_PATH    the .p8 file, mounted into the container
    APNS_KEY_ID      the key's ten-character id
    APNS_TEAM_ID     the developer team id
    APNS_BUNDLE_ID   the iOS app's bundle id, sent as the apns-topic

Push is optional. With none of that configured every call here is a no-op, so
the server runs exactly as it does today.
"""

import asyncio
import base64
import json
import logging
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils

from backend.config import (
    APNS_KEY_PATH, APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID, APNS_USE_SANDBOX,
)

log = logging.getLogger("plex-support.apns")

_HOST = (
    "https://api.sandbox.push.apple.com"
    if APNS_USE_SANDBOX
    else "https://api.push.apple.com"
)

# Apple rejects auth tokens regenerated more often than once every 20 minutes,
# and refuses ones older than an hour. Refreshing at 45 minutes sits safely
# inside both bounds.
_TOKEN_TTL = 45 * 60

_cached_token: str = ""
_cached_at: float = 0.0
_token_lock = asyncio.Lock()


def is_configured() -> bool:
    return bool(APNS_KEY_PATH and APNS_KEY_ID and APNS_TEAM_ID and APNS_BUNDLE_ID)


def _b64(raw: bytes) -> str:
    """base64url without padding, as JWT requires."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _sign(signing_input: bytes) -> bytes:
    """ES256 signature in JOSE form.

    `cryptography` returns a DER-encoded signature, but JWT wants the raw
    r || s pair, each left-padded to 32 bytes. Passing the DER bytes straight
    through produces a token Apple rejects as malformed.
    """
    with open(APNS_KEY_PATH, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)

    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = asym_utils.decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


async def _auth_token() -> str:
    global _cached_token, _cached_at

    async with _token_lock:
        if _cached_token and time.time() - _cached_at < _TOKEN_TTL:
            return _cached_token

        header = _b64(json.dumps({"alg": "ES256", "kid": APNS_KEY_ID}).encode())
        payload = _b64(json.dumps({"iss": APNS_TEAM_ID, "iat": int(time.time())}).encode())
        signing_input = f"{header}.{payload}".encode()

        # Reading and parsing the key is blocking work; keep it off the loop.
        signature = await asyncio.to_thread(_sign, signing_input)

        _cached_token = f"{header}.{payload}.{_b64(signature)}"
        _cached_at = time.time()
        return _cached_token


async def send(device_token: str, title: str, body: str, data: dict | None = None) -> str:
    """Push to one device.

    Returns "ok", "gone" (the token is dead and should be dropped), or "error".
    Never raises — a failed notification must not disturb the fix that
    triggered it.
    """
    if not is_configured():
        return "error"

    try:
        payload = {
            "aps": {
                "alert": {"title": title, "body": body},
                "sound": "default",
            },
        }
        if data:
            payload.update(data)

        jwt = await _auth_token()

        # APNs is HTTP/2 only. httpx needs its h2 extra for this to work at all.
        async with httpx.AsyncClient(http2=True, timeout=10) as c:
            resp = await c.post(
                f"{_HOST}/3/device/{device_token}",
                headers={
                    "authorization": f"bearer {jwt}",
                    "apns-topic": APNS_BUNDLE_ID,
                    "apns-push-type": "alert",
                    "apns-priority": "10",
                    "apns-expiration": str(int(time.time()) + 3600),
                },
                json=payload,
            )

        if resp.status_code == 200:
            return "ok"

        reason = ""
        try:
            reason = resp.json().get("reason", "")
        except Exception:
            reason = resp.text[:200]

        # 410 means the app was uninstalled; BadDeviceToken means it was never
        # valid for this environment. Either way the token is dead to us.
        if resp.status_code == 410 or reason in ("Unregistered", "BadDeviceToken"):
            log.info(f"Dropping dead device token: {reason or resp.status_code}")
            return "gone"

        log.warning(f"APNs rejected push: {resp.status_code} {reason}")
        return "error"

    except Exception as e:
        log.warning(f"APNs send failed: {e}")
        return "error"
