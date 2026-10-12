from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Notification, User
from app.schemas import NotificationOut
from app.security import current_user
from app.timeutil import utcnow

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread: bool = Query(False, description="Only unread alerts"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100)))


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Not found.")
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return n
