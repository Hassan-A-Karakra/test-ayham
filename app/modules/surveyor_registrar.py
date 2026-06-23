from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from ..core import clean, db, get_application_or_404, log_event, now, task_number
from ..schemas import RegistrarReviewRequest, StaffCreate, SurveyMilestoneRequest, SurveyReportCreate
from ..security import require_staff, require_surveyor_or_staff

router = APIRouter(tags=["Student 3 - Surveyor and Registrar"])


@router.post("/staff/", status_code=201)
def create_staff(payload: StaffCreate, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    data = payload.model_dump()
    data["created_at"] = now()
    try:
        result = db().staff_members.insert_one(data)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Staff code already exists") from exc
    data["_id"] = result.inserted_id
    return clean(data)


@router.get("/staff/{staff_id}")
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


@router.post("/applications/{application_id}/auto-assign-surveyor")
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


@router.patch("/applications/{application_id}/survey-milestone")
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


@router.post("/applications/{application_id}/survey-report", status_code=201)
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


@router.patch("/applications/{application_id}/registrar-review")
def registrar_review(application_id: str, payload: RegistrarReviewRequest, user: dict[str, Any] = Depends(require_staff)) -> dict[str, Any]:
    app_doc = get_application_or_404(application_id)
    review = payload.model_dump() | {"reviewed_at": now(), "reviewed_by": user["sub"]}
    db().land_applications.update_one({"_id": app_doc["_id"]}, {"$set": {"registrar_review": review, "timestamps.updated_at": now()}, "$push": {"internal.notes": payload.notes}})
    log_event(app_doc["_id"], "registrar_reviewed", "registrar", payload.registrar_id, {"decision": payload.decision})
    return clean(get_application_or_404(application_id))
