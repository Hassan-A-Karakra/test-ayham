from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from ..core import clean, db, get_application_or_404, log_event, now, oid
from ..schemas import ApplicantCreate, CommentCreate, DocumentInput, ObjectionCreate
from ..security import current_user

router = APIRouter(tags=["Student 2 - Applicant Portal"])


@router.post("/applicants/", status_code=201)
def create_applicant(payload: ApplicantCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    data = payload.model_dump()
    data["linked_applications"] = []
    data["stats"] = {"total_applications": 0, "approved_applications": 0, "pending_applications": 0}
    data["created_at"] = now()
    try:
        result = db().applicants.insert_one(data)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="National ID already exists") from exc
    data["_id"] = result.inserted_id
    return clean(data)


@router.get("/applicants/{applicant_id}")
def get_applicant(applicant_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    doc = db().applicants.find_one({"_id": oid(applicant_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Applicant not found")
    if user["role"] == "applicant":
        doc.pop("privacy_settings", None)
    return clean(doc)


@router.get("/applicants/{applicant_id}/applications")
def applicant_applications(applicant_id: str, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    rows = db().land_applications.find({"applicant_ref.applicant_id": applicant_id}).sort("timestamps.submitted_at", DESCENDING)
    return clean(list(rows))


@router.post("/applications/{application_id}/documents", status_code=201)
def add_document(application_id: str, payload: DocumentInput, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    document = payload.model_dump() | {"uploaded_at": now(), "uploaded_by": user["sub"]}
    db().application_documents.insert_one({"application_id": app_doc["_id"], **document})
    db().land_applications.update_one({"_id": app_doc["_id"]}, {"$push": {"required_documents": document}, "$set": {"timestamps.updated_at": now()}})
    log_event(app_doc["_id"], "document_uploaded", user["role"], user["sub"], {"document_type": payload.document_type})
    return clean(document)


@router.post("/applications/{application_id}/comments", status_code=201)
def add_comment(application_id: str, payload: CommentCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    comment = payload.model_dump() | {"created_at": now()}
    db().land_applications.update_one({"_id": app_doc["_id"]}, {"$push": {"comments": comment}, "$set": {"timestamps.updated_at": now()}})
    log_event(app_doc["_id"], "comment_added", payload.author_type, payload.author_id, {})
    return clean(comment)


@router.post("/applications/{application_id}/objections", status_code=201)
def add_objection(application_id: str, payload: ObjectionCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    objection = payload.model_dump() | {"application_id": app_doc["_id"], "status": "submitted", "created_at": now()}
    result = db().objections.insert_one(objection)
    objection["_id"] = result.inserted_id
    db().land_applications.update_one(
        {"_id": app_doc["_id"]},
        {"$set": {"objection.has_objection": True, "status": "under_objection", "workflow.current_state": "under_objection", "workflow.allowed_next": ["legal_review", "on_hold", "rejected"], "timestamps.updated_at": now()}, "$push": {"objection.objection_ids": result.inserted_id}},
    )
    db().parcels.update_one({"_id": app_doc["parcel_ref"]["parcel_id"]}, {"$set": {"dispute_state": "under_objection"}})
    log_event(app_doc["_id"], "objection_submitted", user["role"], user["sub"], {"objection_id": str(result.inserted_id)})
    return clean(objection)


@router.get("/applications/{application_id}/timeline")
def application_timeline(application_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    logs = db().performance_logs.find_one({"application_id": app_doc["_id"]}) or {"event_stream": []}
    return clean({"timeline": app_doc.get("timeline", []), "audit_events": logs.get("event_stream", [])})
