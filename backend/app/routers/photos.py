"""Photos taken with the phone camera or picked from the gallery.

- patient: to recognise the right person (on the ASHA's register and at the hospital)
- prescription: the doctor's paper prescription, kept with the record
- user: an ASHA's own photo at sign-up, so the district office can check she is real

Photos are resized on the phone and kept in the database. Only people who may see the
patient (or, for a user photo, that user and their district office) can open them.
"""

import base64
import binascii
import re

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import get_patient_for
from app.db import get_db
from app.errors import ApiError
from app.models import AccessRequest, AuditLog, Patient, Photo, Prescription, User
from app.rules import PHOTO_MAX_BYTES, PHOTO_TYPES, Role
from app.schemas import PhotoIn, PhotoOut
from app.security import current_user_any, current_viewer
from app.workflow import commit

router = APIRouter(prefix="/photos", tags=["photos"])
DATA_URL = re.compile(r"^data:(image/[a-z]+);base64,(.+)$", re.S)


def _decode(data_url: str) -> tuple[str, bytes]:
    m = DATA_URL.match(data_url)
    if not m or m.group(1) not in PHOTO_TYPES:
        raise ApiError(422, "VALIDATION_ERROR", "Send a JPEG, PNG or WebP photo.", {"fields": {"data_url": "Not a photo"}})
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "The photo could not be read.") from exc
    if len(data) > PHOTO_MAX_BYTES:
        raise ApiError(413, "PHOTO_TOO_LARGE", "The photo is too large. Please try again (it is resized automatically).")
    magic = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"RIFF": "image/webp"}
    if not any(data.startswith(sig) for sig in magic):
        raise ApiError(422, "VALIDATION_ERROR", "This file is not a photo.")
    return m.group(1), data


@router.post("", response_model=PhotoOut, status_code=201)
def upload(body: PhotoIn, user: User = Depends(current_user_any), db: Session = Depends(get_db)) -> PhotoOut:
    content_type, data = _decode(body.data_url)
    if body.owner_type == "user":
        owner_id = user.id  # anyone, even while waiting for approval, may add their own photo
    else:
        if not user.approved or user.role != Role.WORKER:
            raise ApiError(403, "FORBIDDEN", "Only the patient's ASHA can add this photo.")
        if body.owner_type == "patient":
            patient = get_patient_for(db, user, body.owner_id or "")
            owner_id = patient.id
        else:
            rx = db.get(Prescription, body.owner_id or "")
            if rx is None:
                raise ApiError(404, "NOT_FOUND", "Not found.")
            get_patient_for(db, user, rx.patient_id)
            owner_id = rx.id
    photo = Photo(owner_type=body.owner_type, owner_id=owner_id, content_type=content_type, data=data,
                  uploaded_by_id=user.id)
    db.add(photo)
    db.flush()
    # The newest photo becomes the current one.
    if body.owner_type == "user":
        user.photo_id = photo.id
        pending = db.scalar(select(AccessRequest).where(AccessRequest.user_id == user.id,
                                                       AccessRequest.status == "PENDING"))
        if pending is not None:
            pending.photo_id = photo.id
    elif body.owner_type == "patient":
        db.get(Patient, owner_id).photo_id = photo.id
    else:
        db.get(Prescription, owner_id).photo_id = photo.id
    db.add(AuditLog(actor_id=user.id, action=f"PHOTO_{body.owner_type.upper()}", target_type="photo", target_id=photo.id))
    commit(db)
    return PhotoOut(id=photo.id)


def _may_see(db: Session, viewer: User | Patient, photo: Photo) -> bool:
    if isinstance(viewer, Patient):
        if photo.owner_type == "patient":
            return photo.owner_id == viewer.id
        if photo.owner_type == "prescription":
            rx = db.get(Prescription, photo.owner_id)
            return rx is not None and rx.patient_id == viewer.id
        return False
    if not viewer.approved:  # waiting for approval: only their own photo
        return photo.owner_type == "user" and photo.owner_id == viewer.id
    if photo.owner_type == "user":
        owner = db.get(User, photo.owner_id)
        return owner is not None and (owner.id == viewer.id or (
            viewer.role == Role.COORDINATOR and owner.district.lower() == viewer.district.lower()))
    patient_id = photo.owner_id
    if photo.owner_type == "prescription":
        rx = db.get(Prescription, photo.owner_id)
        patient_id = rx.patient_id if rx else ""
    try:
        get_patient_for(db, viewer, patient_id)
    except ApiError:
        return False
    return True


@router.get("/{photo_id}")
def get_photo(photo_id: str, viewer: User | Patient = Depends(current_viewer), db: Session = Depends(get_db)) -> Response:
    photo = db.get(Photo, photo_id)
    if photo is None or not _may_see(db, viewer, photo):
        raise ApiError(404, "NOT_FOUND", "Not found.")
    return Response(content=photo.data, media_type=photo.content_type,
                    headers={"Cache-Control": "private, max-age=86400"})

