"""
Announcement endpoints for the High School Management System API
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementPayload(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    expires_at: str
    starts_at: Optional[str] = None


def _to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(date_value: Optional[str], field_name: str, required: bool = False) -> Optional[datetime]:
    if not date_value:
        if required:
            raise HTTPException(status_code=422, detail=f"{field_name} is required")
        return None

    try:
        normalized = date_value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a valid ISO 8601 date") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _require_logged_user(teacher_username: Optional[str]) -> Dict[str, Any]:
    if not teacher_username:
        raise HTTPException(status_code=401, detail="Authentication required for this action")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


def _serialize_announcement(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["_id"],
        "message": doc["message"],
        "starts_at": doc.get("starts_at"),
        "expires_at": doc["expires_at"],
        "created_by": doc.get("created_by")
    }


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """List currently active announcements for public display."""
    now_iso = _to_utc_iso(datetime.now(timezone.utc))
    query = {
        "expires_at": {"$gt": now_iso},
        "$or": [
            {"starts_at": None},
            {"starts_at": {"$exists": False}},
            {"starts_at": {"$lte": now_iso}}
        ]
    }

    docs = announcements_collection.find(query).sort([("starts_at", 1), ("expires_at", 1)])
    return [_serialize_announcement(doc) for doc in docs]


@router.get("/manage", response_model=List[Dict[str, Any]])
def list_announcements_for_management(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """List all announcements for management. Requires logged-in user."""
    _require_logged_user(teacher_username)
    docs = announcements_collection.find({}).sort([("expires_at", 1)])
    return [_serialize_announcement(doc) for doc in docs]


@router.post("", response_model=Dict[str, Any])
def create_announcement(payload: AnnouncementPayload, teacher_username: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Create a new announcement. Requires logged-in user."""
    teacher = _require_logged_user(teacher_username)

    starts_at_dt = _parse_iso_datetime(payload.starts_at, "starts_at", required=False)
    expires_at_dt = _parse_iso_datetime(payload.expires_at, "expires_at", required=True)

    if starts_at_dt and starts_at_dt >= expires_at_dt:
        raise HTTPException(status_code=422, detail="starts_at must be before expires_at")

    announcement_id = f"announcement-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    doc = {
        "_id": announcement_id,
        "message": payload.message.strip(),
        "starts_at": _to_utc_iso(starts_at_dt) if starts_at_dt else None,
        "expires_at": _to_utc_iso(expires_at_dt),
        "created_by": teacher["username"]
    }

    announcements_collection.insert_one(doc)
    return _serialize_announcement(doc)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement. Requires logged-in user."""
    _require_logged_user(teacher_username)

    existing = announcements_collection.find_one({"_id": announcement_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Announcement not found")

    starts_at_dt = _parse_iso_datetime(payload.starts_at, "starts_at", required=False)
    expires_at_dt = _parse_iso_datetime(payload.expires_at, "expires_at", required=True)

    if starts_at_dt and starts_at_dt >= expires_at_dt:
        raise HTTPException(status_code=422, detail="starts_at must be before expires_at")

    update_data = {
        "message": payload.message.strip(),
        "starts_at": _to_utc_iso(starts_at_dt) if starts_at_dt else None,
        "expires_at": _to_utc_iso(expires_at_dt)
    }

    announcements_collection.update_one({"_id": announcement_id}, {"$set": update_data})
    updated = announcements_collection.find_one({"_id": announcement_id})
    return _serialize_announcement(updated)


@router.delete("/{announcement_id}", response_model=Dict[str, str])
def delete_announcement(announcement_id: str, teacher_username: Optional[str] = Query(None)) -> Dict[str, str]:
    """Delete an announcement. Requires logged-in user."""
    _require_logged_user(teacher_username)

    result = announcements_collection.delete_one({"_id": announcement_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted successfully"}
