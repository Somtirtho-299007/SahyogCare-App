"""Creates the first real coordinator accounts from SAHYOG_COORDINATOR_EMAILS."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.rules import Role

log = logging.getLogger("sahyogcare.accounts")


def ensure_coordinators(db: Session) -> int:
    """Add a coordinator account for each configured email that has none. Safe to run every start."""
    added = 0
    for email in settings.coordinator_email_list:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            db.add(User(email=email, name=email.split("@")[0], role=Role.COORDINATOR,
                        district=settings.coordinator_district))
            added += 1
        elif not user.is_active:
            log.warning("Configured coordinator %s is switched off; leaving it off.", email)
    db.commit()
    if added:
        log.info("Added %d coordinator account(s) from SAHYOG_COORDINATOR_EMAILS.", added)
    return added
