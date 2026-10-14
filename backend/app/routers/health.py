from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.db import get_db
from app.errors import ApiError
from app.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # database down or misconfigured
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The database is not reachable.") from exc
    from app.messaging import check_sms, email_enabled

    # Which outside services are set up (never the keys): helps find why an SMS or email
    # did not arrive. "log-only" means codes go to the server log, not to phones.
    return HealthOut(status="ok", database="ok", version=__version__, sms=check_sms(),
                     email="on" if email_enabled() else "off")
