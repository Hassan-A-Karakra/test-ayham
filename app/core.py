from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from .database import get_db


WORKFLOW: dict[str, set[str]] = {
    "submitted": {"pre_checked", "missing_documents", "rejected", "on_hold", "under_objection"},
    "pre_checked": {"survey_required", "legal_review", "missing_documents", "rejected", "on_hold", "under_objection"},
    "survey_required": {"surveyed", "rejected", "on_hold", "under_objection"},
    "surveyed": {"legal_review", "rejected", "on_hold", "under_objection"},
    "legal_review": {"approved", "rejected", "on_hold", "under_objection", "missing_documents"},
    "approved": {"certificate_issued", "closed"},
    "certificate_issued": {"closed"},
    "on_hold": {"submitted", "pre_checked", "survey_required", "legal_review", "rejected"},
    "missing_documents": {"submitted", "pre_checked", "rejected", "on_hold"},
    "under_objection": {"legal_review", "rejected", "on_hold"},
    "rejected": set(),
    "closed": set(),
}


def now() -> datetime:
    return datetime.now(UTC)


def db():
    return get_db()


def oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail=f"Invalid ObjectId: {value}")
    return ObjectId(value)


def clean(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    return value


def timestamped_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}-{stamp}"


def app_number() -> str:
    return timestamped_id("LRMIS")


def cert_number() -> str:
    return timestamped_id("CERT")


def task_number() -> str:
    return timestamped_id("SURV")


def parcel_code(parcel: dict[str, Any]) -> str:
    return f"{parcel['zone_id']}-B{parcel['block_number']}-BA{parcel['basin_number']}-P{parcel['parcel_number']}"


def log_event(application_oid: ObjectId, event_type: str, actor_type: str, actor_id: str, meta: dict[str, Any] | None = None) -> None:
    db().performance_logs.update_one(
        {"application_id": application_oid},
        {
            "$push": {
                "event_stream": {
                    "type": event_type,
                    "by": {"actor_type": actor_type, "actor_id": actor_id},
                    "at": now(),
                    "meta": meta or {},
                }
            },
            "$setOnInsert": {"computed_kpis": {"certificate_issued": False}},
        },
        upsert=True,
    )


def get_application_or_404(application_id: str) -> dict[str, Any]:
    query: dict[str, Any] = {"application_id": application_id}
    if ObjectId.is_valid(application_id):
        query = {"$or": [{"_id": ObjectId(application_id)}, {"application_id": application_id}]}
    doc = db().land_applications.find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Application not found")
    return doc
