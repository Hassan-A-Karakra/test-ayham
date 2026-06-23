from typing import Any, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from ..core import WORKFLOW, app_number, cert_number, clean, db, get_application_or_404, log_event, now, oid, parcel_code
from ..schemas import ApplicationCreate, ApplicationStatus, HoldRequest, RejectRequest, TransitionRequest
from ..security import current_user, require_staff

LiteralSort = Literal["asc", "desc"]

router = APIRouter(tags=["Student 1 - Land Application Management"])


def has_verified_ownership_doc(application_doc: dict[str, Any]) -> bool:
    ownership_types = {"ownership_deed", "sale_contract", "inheritance_document", "court_decision"}
    return any(
        doc.get("document_type") in ownership_types and doc.get("status") in {"uploaded", "pending_review", "verified"}
        for doc in application_doc.get("required_documents", [])
    )


def validate_transition(application_doc: dict[str, Any], target_state: str, payload: TransitionRequest | None = None) -> None:
    current = application_doc["status"]
    if target_state not in WORKFLOW.get(current, set()):
        raise HTTPException(status_code=409, detail=f"Invalid transition from {current} to {target_state}")

    parcel_ref = application_doc.get("parcel_ref", {})
    if target_state == "pre_checked":
        if not application_doc.get("applicant_ref") or not parcel_ref.get("parcel_number"):
            raise HTTPException(status_code=422, detail="Applicant and parcel information must be complete")
    if target_state == "survey_required" and not parcel_ref.get("parcel_id"):
        raise HTTPException(status_code=422, detail="Parcel location must be valid before survey")
    if target_state == "surveyed":
        report = db().survey_reports.find_one({"application_id": application_doc["_id"]})
        if not report:
            raise HTTPException(status_code=422, detail="Survey report is required before moving to surveyed")
    if target_state == "legal_review" and not has_verified_ownership_doc(application_doc):
        raise HTTPException(status_code=422, detail="Ownership documents are required before legal review")
    if target_state == "approved":
        review = application_doc.get("registrar_review", {})
        if review.get("decision") not in {"accepted", "approved_for_certificate"}:
            raise HTTPException(status_code=422, detail="Legal review must be completed before approval")
    if target_state == "certificate_issued" and current != "approved":
        raise HTTPException(status_code=422, detail="Certificate can only be issued after approval")
    if target_state == "rejected" and (not payload or not payload.notes):
        raise HTTPException(status_code=422, detail="Rejected applications must include a rejection reason")
    if target_state == "under_objection" and not application_doc.get("objection", {}).get("has_objection"):
        raise HTTPException(status_code=422, detail="Applications move under objection only after an objection exists")


def transition_application(application_doc: dict[str, Any], payload: TransitionRequest) -> dict[str, Any]:
    validate_transition(application_doc, payload.target_state.value, payload)
    timestamp_key = f"{payload.target_state.value}_at"
    update = {
        "$set": {
            "status": payload.target_state.value,
            "workflow.current_state": payload.target_state.value,
            "workflow.allowed_next": sorted(WORKFLOW[payload.target_state.value]),
            f"timestamps.{timestamp_key}": now(),
            "timestamps.updated_at": now(),
        },
        "$push": {
            "timeline": {
                "state": payload.target_state.value,
                "at": now(),
                "actor_type": payload.actor_type,
                "actor_id": payload.actor_id,
                "notes": payload.notes,
                "meta": payload.meta,
            }
        },
    }
    if payload.notes:
        update["$push"]["internal.notes"] = payload.notes
    db().land_applications.update_one({"_id": application_doc["_id"]}, update)
    log_event(application_doc["_id"], payload.target_state.value, payload.actor_type, payload.actor_id, payload.meta)
    return get_application_or_404(str(application_doc["_id"]))


@router.post("/applications/", status_code=201)
def create_application(
    payload: ApplicationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if idempotency_key:
        existing = db().land_applications.find_one({"idempotency_key": idempotency_key})
        if existing:
            return clean(existing)

    parcel_data = payload.parcel.model_dump()
    code = parcel_code(parcel_data)
    parcel_doc = {
        **parcel_data,
        "parcel_code": code,
        "registration_status": "pending",
        "dispute_state": "none",
        "updated_at": now(),
    }
    db().parcels.update_one(
        {"parcel_code": code},
        {"$set": parcel_doc, "$setOnInsert": {"created_at": now(), "current_owner_refs": []}},
        upsert=True,
    )
    parcel = db().parcels.find_one({"parcel_code": code})
    assert parcel is not None

    ts = {
        "submitted_at": now(),
        "pre_checked_at": None,
        "survey_required_at": None,
        "surveyed_at": None,
        "legal_review_at": None,
        "approved_at": None,
        "certificate_issued_at": None,
        "closed_at": None,
        "updated_at": now(),
    }
    application_doc = {
        "application_id": app_number(),
        "application_type": payload.application_type.value,
        "status": "submitted",
        "priority": payload.priority,
        "applicant_ref": payload.applicant_ref.model_dump(),
        "parcel_ref": {
            "parcel_id": parcel["_id"],
            "parcel_number": parcel["parcel_number"],
            "block_number": parcel["block_number"],
            "basin_number": parcel["basin_number"],
            "zone_id": parcel["zone_id"],
        },
        "description": payload.description,
        "tags": payload.tags,
        "workflow": {"current_state": "submitted", "allowed_next": sorted(WORKFLOW["submitted"]), "transition_rules_version": "v1.0"},
        "required_documents": [doc.model_dump() for doc in payload.required_documents],
        "timestamps": ts,
        "assignment": {"assigned_surveyor_id": None, "assigned_registrar_id": None, "assignment_policy": "zone+workload+availability"},
        "objection": {"has_objection": False, "objection_ids": []},
        "internal": {"notes": [], "visibility": "staff_only"},
        "timeline": [{"state": "submitted", "at": now(), "actor_type": user["role"], "actor_id": user["sub"], "notes": "Application submitted", "meta": {}}],
        "comments": [],
        "certificate_state": None,
        "idempotency_key": idempotency_key,
    }
    try:
        result = db().land_applications.insert_one(application_doc)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Duplicate application or idempotency key") from exc
    application_doc["_id"] = result.inserted_id
    db().applicants.update_one(
        {"_id": oid(payload.applicant_ref.applicant_id)},
        {"$addToSet": {"linked_applications": result.inserted_id}, "$inc": {"stats.total_applications": 1, "stats.pending_applications": 1}},
    )
    log_event(result.inserted_id, "submitted", user["role"], user["sub"], {"channel": "web"})
    return clean(application_doc)


@router.get("/applications/")
def list_applications(
    status_filter: str | None = Query(default=None, alias="status"),
    application_type: str | None = None,
    zone: str | None = None,
    applicant: str | None = None,
    parcel_number: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = "timestamps.submitted_at",
    sort_dir: LiteralSort = Query(default="desc"),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if status_filter:
        query["status"] = status_filter
    if application_type:
        query["application_type"] = application_type
    if zone:
        query["parcel_ref.zone_id"] = zone
    if applicant:
        query["applicant_ref.applicant_id"] = applicant
    if parcel_number:
        query["parcel_ref.parcel_number"] = parcel_number
    direction = DESCENDING if sort_dir == "desc" else ASCENDING
    total = db().land_applications.count_documents(query)
    rows = db().land_applications.find(query).sort(sort_by, direction).skip((page - 1) * page_size).limit(page_size)
    return {"items": clean(list(rows)), "page": page, "page_size": page_size, "total": total}


@router.get("/applications/{application_id}")
def get_application(application_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    application_doc = get_application_or_404(application_id)
    parcel = db().parcels.find_one({"_id": application_doc["parcel_ref"]["parcel_id"]})
    logs = db().performance_logs.find_one({"application_id": application_doc["_id"]})
    certificate = db().certificates.find_one({"application_id": application_doc["_id"]})
    tasks = list(db().survey_tasks.find({"application_id": application_doc["_id"]}))
    return clean({**application_doc, "parcel": parcel, "audit_log": logs, "certificate": certificate, "survey_tasks": tasks})


@router.patch("/applications/{application_id}/transition")
def transition(application_id: str, payload: TransitionRequest, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    application_doc = get_application_or_404(application_id)
    return clean(transition_application(application_doc, payload))


@router.post("/applications/{application_id}/hold")
def hold_application(application_id: str, payload: HoldRequest, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    transition_payload = TransitionRequest(target_state=ApplicationStatus.on_hold, actor_type=user["role"], actor_id=user["sub"], notes=payload.reason)
    return clean(transition_application(app_doc, transition_payload))


@router.post("/applications/{application_id}/reject")
def reject_application(application_id: str, payload: RejectRequest, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    transition_payload = TransitionRequest(target_state=ApplicationStatus.rejected, actor_type=user["role"], actor_id=user["sub"], notes=payload.reason)
    return clean(transition_application(app_doc, transition_payload))


@router.post("/applications/{application_id}/certificate")
def issue_certificate(application_id: str, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    if app_doc["status"] != "approved":
        raise HTTPException(status_code=422, detail="Application must be approved before certificate issuance")
    existing = db().certificates.find_one({"application_id": app_doc["_id"]})
    if existing:
        return clean(existing)
    cert = {
        "certificate_id": cert_number(),
        "application_id": app_doc["_id"],
        "parcel_id": app_doc["parcel_ref"]["parcel_id"],
        "certificate_type": "ownership_certificate",
        "status": "issued",
        "issued_to": {"applicant_id": app_doc["applicant_ref"]["applicant_id"], "full_name": None},
        "issued_at": now(),
        "issued_by": user["sub"],
        "verification": {"qr_code_url": f"/certificates/{application_id}/verify", "digital_signature_stub": f"signed-{app_doc['application_id']}"},
    }
    result = db().certificates.insert_one(cert)
    cert["_id"] = result.inserted_id
    db().land_applications.update_one(
        {"_id": app_doc["_id"]},
        {"$set": {"status": "certificate_issued", "workflow.current_state": "certificate_issued", "workflow.allowed_next": ["closed"], "certificate_state": "issued", "timestamps.certificate_issued_at": now(), "timestamps.updated_at": now()}},
    )
    log_event(app_doc["_id"], "certificate_issued", user["role"], user["sub"], {"certificate_id": cert["certificate_id"]})
    return clean(cert)
