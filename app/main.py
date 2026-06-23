from datetime import UTC, datetime
import csv
from io import StringIO
import os
from typing import Any, Literal

from bson import ObjectId
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from .database import ensure_indexes, get_db
from .schemas import (
    ApplicantCreate,
    ApplicationCreate,
    ApplicationStatus,
    CommentCreate,
    DocumentInput,
    HoldRequest,
    LoginRequest,
    ObjectionCreate,
    RegistrarReviewRequest,
    RejectRequest,
    StaffCreate,
    SurveyMilestoneRequest,
    SurveyReportCreate,
    TransitionRequest,
)
from .security import USERS, create_token, current_user, require_staff, require_surveyor_or_staff

LiteralSort = Literal["asc", "desc"]

app = FastAPI(
    title="LRMIS - Land Registration Management Information System",
    description="FastAPI + PyMongo backend for land registration workflow, survey tasks, maps, and analytics.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_DIST = os.path.join(STATIC_DIR, "dist")
FRONTEND_ASSETS = os.path.join(FRONTEND_DIST, "assets")


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


def app_number() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"LRMIS-{stamp}"


def cert_number() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"CERT-{stamp}"


def task_number() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"SURV-{stamp}"


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


def required_docs_verified(application_doc: dict[str, Any]) -> bool:
    docs = application_doc.get("required_documents", [])
    required = [doc for doc in docs if doc.get("required", True)]
    return bool(required) and all(doc.get("status") in {"verified", "pending_review", "uploaded"} for doc in required)


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


@app.on_event("startup")
def startup() -> None:
    if os.getenv("CREATE_INDEXES", "true").lower() == "true":
        try:
            ensure_indexes()
        except Exception as exc:
            print(f"MongoDB indexes were not created: {exc}")


@app.get("/")
def root() -> FileResponse:
    built_index = os.path.join(FRONTEND_DIST, "index.html")
    source_index = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(built_index if os.path.exists(built_index) else source_index)


@app.get("/health")
def health() -> dict[str, Any]:
    db().command("ping")
    return {"status": "ok", "database": os.getenv("MONGO_DB", "lrmis")}


@app.post("/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    user = USERS.get(payload.username)
    if not user or user["password"] != payload.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return {"access_token": create_token(payload.username, user["role"]), "token_type": "bearer", "user": {"username": payload.username, "role": user["role"], "name": user["name"]}}


@app.get("/auth/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user


@app.post("/applicants/", status_code=201)
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


@app.get("/applicants/{applicant_id}")
def get_applicant(applicant_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    doc = db().applicants.find_one({"_id": oid(applicant_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Applicant not found")
    if user["role"] == "applicant":
        doc.pop("privacy_settings", None)
    return clean(doc)


@app.get("/applicants/{applicant_id}/applications")
def applicant_applications(applicant_id: str, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    rows = db().land_applications.find({"applicant_ref.applicant_id": applicant_id}).sort("timestamps.submitted_at", DESCENDING)
    return clean(list(rows))


@app.post("/applications/", status_code=201)
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


@app.get("/applications/")
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
    rows = (
        db().land_applications.find(query)
        .sort(sort_by, direction)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return {"items": clean(list(rows)), "page": page, "page_size": page_size, "total": total}

@app.get("/applications/{application_id}")
def get_application(application_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    application_doc = get_application_or_404(application_id)
    parcel = db().parcels.find_one({"_id": application_doc["parcel_ref"]["parcel_id"]})
    logs = db().performance_logs.find_one({"application_id": application_doc["_id"]})
    certificate = db().certificates.find_one({"application_id": application_doc["_id"]})
    tasks = list(db().survey_tasks.find({"application_id": application_doc["_id"]}))
    return clean({**application_doc, "parcel": parcel, "audit_log": logs, "certificate": certificate, "survey_tasks": tasks})


@app.patch("/applications/{application_id}/transition")
def transition(application_id: str, payload: TransitionRequest, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    application_doc = get_application_or_404(application_id)
    return clean(transition_application(application_doc, payload))


@app.post("/applications/{application_id}/hold")
def hold_application(application_id: str, payload: HoldRequest, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    transition_payload = TransitionRequest(target_state=ApplicationStatus.on_hold, actor_type=user["role"], actor_id=user["sub"], notes=payload.reason)
    return clean(transition_application(app_doc, transition_payload))


@app.post("/applications/{application_id}/reject")
def reject_application(application_id: str, payload: RejectRequest, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    transition_payload = TransitionRequest(target_state=ApplicationStatus.rejected, actor_type=user["role"], actor_id=user["sub"], notes=payload.reason)
    return clean(transition_application(app_doc, transition_payload))


@app.post("/applications/{application_id}/certificate")
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


@app.post("/applications/{application_id}/documents", status_code=201)
def add_document(application_id: str, payload: DocumentInput, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    document = payload.model_dump() | {"uploaded_at": now(), "uploaded_by": user["sub"]}
    db().application_documents.insert_one({"application_id": app_doc["_id"], **document})
    db().land_applications.update_one({"_id": app_doc["_id"]}, {"$push": {"required_documents": document}, "$set": {"timestamps.updated_at": now()}})
    log_event(app_doc["_id"], "document_uploaded", user["role"], user["sub"], {"document_type": payload.document_type})
    return clean(document)


@app.post("/applications/{application_id}/comments", status_code=201)
def add_comment(application_id: str, payload: CommentCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    comment = payload.model_dump() | {"created_at": now()}
    db().land_applications.update_one({"_id": app_doc["_id"]}, {"$push": {"comments": comment}, "$set": {"timestamps.updated_at": now()}})
    log_event(app_doc["_id"], "comment_added", payload.author_type, payload.author_id, {})
    return clean(comment)


@app.post("/applications/{application_id}/objections", status_code=201)
def add_objection(application_id: str, payload: ObjectionCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    objection = payload.model_dump() | {"application_id": app_doc["_id"], "status": "submitted", "created_at": now()}
    result = db().objections.insert_one(objection)
    objection["_id"] = result.inserted_id
    db().land_applications.update_one(
        {"_id": app_doc["_id"]},
        {"$set": {"objection.has_objection": True, "status": "under_objection", "workflow.current_state": "under_objection", "workflow.allowed_next": sorted(WORKFLOW["under_objection"]), "timestamps.updated_at": now()}, "$push": {"objection.objection_ids": result.inserted_id}},
    )
    db().parcels.update_one({"_id": app_doc["parcel_ref"]["parcel_id"]}, {"$set": {"dispute_state": "under_objection"}})
    log_event(app_doc["_id"], "objection_submitted", user["role"], user["sub"], {"objection_id": str(result.inserted_id)})
    return clean(objection)


@app.get("/applications/{application_id}/timeline")
def application_timeline(application_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    logs = db().performance_logs.find_one({"application_id": app_doc["_id"]}) or {"event_stream": []}
    return clean({"timeline": app_doc.get("timeline", []), "audit_events": logs.get("event_stream", [])})


@app.post("/staff/", status_code=201)
def create_staff(payload: StaffCreate, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    data = payload.model_dump()
    data["created_at"] = now()
    try:
        result = db().staff_members.insert_one(data)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Staff code already exists") from exc
    data["_id"] = result.inserted_id
    return clean(data)


@app.get("/staff/{staff_id}")
def get_staff(staff_id: str, user: dict[str, Any] = Depends(require_surveyor_or_staff)) -> dict[str, Any]:
    query: dict[str, Any] = {"staff_code": staff_id}
    if ObjectId.is_valid(staff_id):
        query = {"$or": [{"_id": ObjectId(staff_id)}, {"staff_code": staff_id}]}
    doc = db().staff_members.find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Staff member not found")
    active_tasks = db().survey_tasks.count_documents({"assigned_surveyor_id": doc["_id"], "status": {"$ne": "registrar_reviewed"}})
    reports = db().survey_reports.count_documents({"surveyor_id": doc["_id"]})
    return clean(doc | {"performance_summary": {"active_tasks": active_tasks, "reports_uploaded": reports}})


@app.post("/applications/{application_id}/auto-assign-surveyor")
def auto_assign(application_id: str, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    zone_id = app_doc["parcel_ref"]["zone_id"]
    application_type = app_doc["application_type"]
    candidates = list(
        db().staff_members.find(
            {
                "role": "surveyor",
                "active": True,
                "$or": [{"coverage.zone_ids": zone_id}, {"coverage.zone_ids": {"$exists": False}}],
            }
        )
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="No available surveyor for this zone")

    def score(member: dict[str, Any]) -> tuple[int, int, str]:
        skills = set(member.get("skills", []))
        workload = member.get("workload", {})
        active = int(workload.get("active_tasks", 0))
        max_tasks = int(workload.get("max_tasks", 10))
        capacity = max(max_tasks - active, 0)
        skill_match = 1 if application_type in skills or "boundary_survey" in skills or "gps_mapping" in skills else 0
        return (-capacity, -skill_match, member.get("staff_code", ""))

    selected = sorted(candidates, key=score)[0]
    task = {
        "task_id": task_number(),
        "application_id": app_doc["_id"],
        "parcel_id": app_doc["parcel_ref"]["parcel_id"],
        "assigned_surveyor_id": selected["_id"],
        "status": "assigned",
        "milestones": [{"type": "assigned", "at": now(), "by": "system", "meta": {"reason": "zone/workload/skill match"}}],
        "field_notes": [],
        "report_uploaded": False,
        "created_at": now(),
    }
    result = db().survey_tasks.insert_one(task)
    task["_id"] = result.inserted_id
    db().staff_members.update_one({"_id": selected["_id"]}, {"$inc": {"workload.active_tasks": 1}})
    db().land_applications.update_one({"_id": app_doc["_id"]}, {"$set": {"assignment.assigned_surveyor_id": selected["_id"], "timestamps.updated_at": now()}})
    log_event(app_doc["_id"], "survey_assigned", "system", "assignment_engine", {"assigned_surveyor": selected["staff_code"]})
    return clean({"task": task, "surveyor": selected})


@app.patch("/applications/{application_id}/survey-milestone")
def survey_milestone(application_id: str, payload: SurveyMilestoneRequest, user: dict[str, Any] = Depends(require_surveyor_or_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    task = db().survey_tasks.find_one({"application_id": app_doc["_id"]})
    if not task:
        raise HTTPException(status_code=404, detail="Survey task not found")
    milestone = {"type": payload.milestone, "at": now(), "by": payload.by, "meta": payload.meta}
    db().survey_tasks.update_one({"_id": task["_id"]}, {"$set": {"status": payload.milestone}, "$push": {"milestones": milestone}})
    log_event(app_doc["_id"], f"survey_{payload.milestone}", user["role"], user["sub"], payload.meta)
    updated = db().survey_tasks.find_one({"_id": task["_id"]})
    return clean(updated)


@app.post("/applications/{application_id}/survey-report", status_code=201)
def survey_report(application_id: str, payload: SurveyReportCreate, user: dict[str, Any] = Depends(require_surveyor_or_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    task = db().survey_tasks.find_one({"application_id": app_doc["_id"]})
    report = payload.model_dump() | {
        "application_id": app_doc["_id"],
        "parcel_id": app_doc["parcel_ref"]["parcel_id"],
        "surveyor_id": task.get("assigned_surveyor_id") if task else None,
        "uploaded_at": now(),
        "uploaded_by": user["sub"],
    }
    result = db().survey_reports.insert_one(report)
    report["_id"] = result.inserted_id
    if task:
        db().survey_tasks.update_one({"_id": task["_id"]}, {"$set": {"report_uploaded": True, "status": "report_uploaded"}, "$push": {"milestones": {"type": "report_uploaded", "at": now(), "by": user["sub"], "meta": {"report_id": str(result.inserted_id)}}}})
    log_event(app_doc["_id"], "survey_report_uploaded", user["role"], user["sub"], {"report_id": str(result.inserted_id)})
    return clean(report)


@app.patch("/applications/{application_id}/registrar-review")
def registrar_review(application_id: str, payload: RegistrarReviewRequest, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    review = payload.model_dump() | {"reviewed_at": now(), "reviewed_by": user["sub"]}
    db().land_applications.update_one({"_id": app_doc["_id"]}, {"$set": {"registrar_review": review, "timestamps.updated_at": now()}, "$push": {"internal.notes": payload.notes}})
    log_event(app_doc["_id"], "registrar_reviewed", "registrar", payload.registrar_id, {"decision": payload.decision})
    return clean(get_application_or_404(application_id))


@app.get("/analytics/kpis")
def kpis(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    total = db().land_applications.count_documents({})
    pending = db().land_applications.count_documents({"status": {"$in": ["submitted", "pre_checked", "survey_required", "surveyed", "legal_review", "missing_documents", "on_hold"]}})
    approved = db().land_applications.count_documents({"status": {"$in": ["approved", "certificate_issued", "closed"]}})
    rejected = db().land_applications.count_documents({"status": "rejected"})
    objections = db().land_applications.count_documents({"status": "under_objection"})
    certificates = db().certificates.count_documents({"status": "issued"})
    avg_pipeline = [
        {"$match": {"timestamps.submitted_at": {"$ne": None}, "timestamps.closed_at": {"$ne": None}}},
        {"$project": {"days": {"$dateDiff": {"startDate": "$timestamps.submitted_at", "endDate": "$timestamps.closed_at", "unit": "day"}}}},
        {"$group": {"_id": None, "avg_days": {"$avg": "$days"}}},
    ]
    avg = list(db().land_applications.aggregate(avg_pipeline))
    return {"total_applications": total, "pending_applications": pending, "approved_applications": approved, "rejected_applications": rejected, "applications_under_objection": objections, "certificates_issued": certificates, "average_processing_days": round(avg[0]["avg_days"], 2) if avg else 0}


@app.get("/analytics/applications-by-status")
def applications_by_status(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return clean(list(db().land_applications.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}])))


@app.get("/analytics/applications-by-zone")
def applications_by_zone(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return clean(list(db().land_applications.aggregate([{"$group": {"_id": "$parcel_ref.zone_id", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}])))


@app.get("/analytics/processing-time")
def processing_time(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    pipeline = [
        {"$match": {"timestamps.submitted_at": {"$ne": None}}},
        {"$project": {"application_type": 1, "end": {"$ifNull": ["$timestamps.closed_at", "$timestamps.updated_at"]}, "start": "$timestamps.submitted_at"}},
        {"$project": {"application_type": 1, "hours": {"$dateDiff": {"startDate": "$start", "endDate": "$end", "unit": "hour"}}}},
        {"$group": {"_id": "$application_type", "avg_hours": {"$avg": "$hours"}, "count": {"$sum": 1}}},
        {"$sort": {"avg_hours": -1}},
    ]
    return clean(list(db().land_applications.aggregate(pipeline)))


@app.get("/analytics/surveyors")
def surveyor_analytics(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    pipeline = [
        {"$match": {"role": "surveyor"}},
        {"$lookup": {"from": "survey_tasks", "localField": "_id", "foreignField": "assigned_surveyor_id", "as": "tasks"}},
        {"$project": {"staff_code": 1, "name": 1, "workload": 1, "task_count": {"$size": "$tasks"}, "completed": {"$size": {"$filter": {"input": "$tasks", "as": "t", "cond": {"$eq": ["$$t.status", "registrar_reviewed"]}}}}}},
        {"$sort": {"task_count": -1}},
    ]
    return clean(list(db().staff_members.aggregate(pipeline)))


@app.get("/analytics/registrars")
def registrar_analytics(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    pipeline = [
        {"$match": {"registrar_review.registrar_id": {"$exists": True}}},
        {"$group": {"_id": "$registrar_review.registrar_id", "reviews": {"$sum": 1}, "approved": {"$sum": {"$cond": [{"$in": ["$registrar_review.decision", ["accepted", "approved_for_certificate"]]}, 1, 0]}}}},
        {"$sort": {"reviews": -1}},
    ]
    return clean(list(db().land_applications.aggregate(pipeline)))


@app.get("/analytics/geofeeds/parcels")
def parcel_geofeed(status_filter: str | None = Query(default=None, alias="status"), zone: str | None = None, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if zone:
        query["zone_id"] = zone
    features = []
    for parcel in db().parcels.find(query):
        app_query: dict[str, Any] = {"parcel_ref.parcel_id": parcel["_id"]}
        if status_filter:
            app_query["status"] = status_filter
        app_doc = db().land_applications.find_one(app_query)
        if status_filter and not app_doc:
            continue
        features.append({"type": "Feature", "geometry": parcel["geometry"], "properties": clean({"parcel_id": parcel["_id"], "parcel_code": parcel.get("parcel_code"), "zone_id": parcel.get("zone_id"), "dispute_state": parcel.get("dispute_state"), "application_status": app_doc.get("status") if app_doc else None})})
    return {"type": "FeatureCollection", "features": features}


@app.get("/analytics/geofeeds/pending-heatmap")
def pending_heatmap(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    pending = {"$in": ["submitted", "pre_checked", "survey_required", "missing_documents", "under_objection"]}
    pipeline = [
        {"$match": {"status": pending}},
        {"$lookup": {"from": "parcels", "localField": "parcel_ref.parcel_id", "foreignField": "_id", "as": "parcel"}},
        {"$unwind": "$parcel"},
        {"$project": {"status": 1, "application_type": 1, "zone_id": "$parcel.zone_id", "geometry": "$parcel.geometry"}},
    ]
    features = []
    for item in db().land_applications.aggregate(pipeline):
        features.append({"type": "Feature", "geometry": item["geometry"], "properties": clean({"application_id": item["_id"], "status": item["status"], "application_type": item["application_type"], "zone_id": item["zone_id"], "weight": 2 if item["status"] == "under_objection" else 1})})
    return {"type": "FeatureCollection", "features": features}


@app.get("/reports/applications.csv")
def applications_csv(user: dict[str, Any] = Depends(require_staff)) -> StreamingResponse:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["application_id", "type", "status", "zone", "parcel_number", "submitted_at"])
    for row in db().land_applications.find({}).sort("timestamps.submitted_at", DESCENDING):
        writer.writerow([row.get("application_id"), row.get("application_type"), row.get("status"), row.get("parcel_ref", {}).get("zone_id"), row.get("parcel_ref", {}).get("parcel_number"), row.get("timestamps", {}).get("submitted_at")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=lrmis_applications.csv"})


if os.path.isdir(FRONTEND_ASSETS):
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str) -> FileResponse:
    if full_path.startswith(("api/", "auth/", "applications/", "applicants/", "staff/", "analytics/", "reports/", "docs", "openapi.json", "redoc")):
        raise HTTPException(status_code=404, detail="Not found")
    built_index = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(built_index):
        return FileResponse(built_index)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
