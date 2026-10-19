import asyncio
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from starlette.responses import StreamingResponse

from apis.core.database import get_db
from apis.core.security import (
    require_app_access_ready,
    assert_app_access_ready,
    get_session_token,
    resolve_user_from_token,
)
from apis.services.realtime_streams import (
    subscribe_notifications,
    unsubscribe_notifications,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

@router.get("")
async def get_user_notifications(current_user: dict = Depends(require_app_access_ready), db=Depends(get_db)):
    user_id = current_user.get("id")
    rows = await db.fetch("SELECT * FROM notifications WHERE user_id=$1 ORDER BY created_at DESC", user_id)
    return [dict(r) for r in rows]

@router.put("/{notification_id}/read")
async def mark_notification_read(notification_id: str, current_user: dict = Depends(require_app_access_ready), db=Depends(get_db)):
    user_id = current_user.get("id")
    row = await db.fetchrow(
        "UPDATE notifications SET is_read=True WHERE id=$1 AND user_id=$2 RETURNING *",
        notification_id, user_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    return dict(row)

@router.post("/mark-all-read")
async def mark_all_notifications_read(current_user: dict = Depends(require_app_access_ready), db=Depends(get_db)):
    user_id = current_user.get("id")
    await db.execute(
        "UPDATE notifications SET is_read=True WHERE user_id=$1 AND is_read=False",
        user_id
    )
    return {"ok": True}


@router.get("/stream")
async def notifications_stream(
    request: Request,
    token: Optional[str] = None,
    db=Depends(get_db),
):
    # Cookie (preferred) -> Authorization header -> legacy ?token= query param.
    effective_token = (
        get_session_token(request)
        or (token.strip() if isinstance(token, str) else "")
        or ""
    )
    if not effective_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        current = await resolve_user_from_token(effective_token, db)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = str(current.get("id"))
    await assert_app_access_ready(db, user_id)

    async def _event_generator():
        queue = await subscribe_notifications(user_id)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await unsubscribe_notifications(user_id, queue)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
