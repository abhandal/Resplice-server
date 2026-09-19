import logging

import httpx
from fastapi import APIRouter, Request, HTTPException

from backend.config import DISCORD_WEBHOOK_URL
from backend.plex_auth import require_user
from backend.fix import get_fix, mark_notified

log = logging.getLogger("plex-support.discord")
router = APIRouter(prefix="/api")


async def _send_webhook(message: str):
    if not DISCORD_WEBHOOK_URL:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(DISCORD_WEBHOOK_URL, json={"content": message})


@router.post("/notify")
async def notify_admin(request: Request):
    user = require_user(request)
    body = await request.json()
    fix_id = body.get("fixId", "")

    fix = get_fix(fix_id)
    if not fix:
        raise HTTPException(404, "Fix request not found")
    if fix.user_id != user["uid"]:
        raise HTTPException(403, "Not your fix request")
    if fix.notified:
        raise HTTPException(400, "Already notified")
    # Without a webhook the send below is a no-op; succeeding anyway would tell
    # the user the admin was notified when nobody was, and burn their one retry.
    if not DISCORD_WEBHOOK_URL:
        raise HTTPException(503, "Admin notifications are not configured on this server")

    await _send_webhook(
        f"**Plex Support** — **{user['name']}** reports **{fix.title}** is stuck\n"
        f"> {fix.stuck_reason}"
    )
    mark_notified(fix_id)
    return {"ok": True}
