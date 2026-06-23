import csv
from io import StringIO
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pymongo import DESCENDING

from ..core import clean, db
from ..security import current_user, require_staff

router = APIRouter(tags=["Group Module - Analytics and Map"])


@router.get("/analytics/kpis")
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
    return {
        "total_applications": total,
        "pending_applications": pending,
        "approved_applications": approved,
        "rejected_applications": rejected,
        "applications_under_objection": objections,
        "certificates_issued": certificates,
        "average_processing_days": round(avg[0]["avg_days"], 2) if avg else 0,
    }


@router.get("/analytics/applications-by-status")
def applications_by_status(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return clean(list(db().land_applications.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}])))


@router.get("/analytics/applications-by-zone")
def applications_by_zone(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return clean(list(db().land_applications.aggregate([{"$group": {"_id": "$parcel_ref.zone_id", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}])))


@router.get("/analytics/processing-time")
def processing_time(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    pipeline = [
        {"$match": {"timestamps.submitted_at": {"$ne": None}}},
        {"$project": {"application_type": 1, "end": {"$ifNull": ["$timestamps.closed_at", "$timestamps.updated_at"]}, "start": "$timestamps.submitted_at"}},
        {"$project": {"application_type": 1, "hours": {"$dateDiff": {"startDate": "$start", "endDate": "$end", "unit": "hour"}}}},
        {"$group": {"_id": "$application_type", "avg_hours": {"$avg": "$hours"}, "count": {"$sum": 1}}},
        {"$sort": {"avg_hours": -1}},
    ]
    return clean(list(db().land_applications.aggregate(pipeline)))


@router.get("/analytics/surveyors")
def surveyor_analytics(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    pipeline = [
        {"$match": {"role": "surveyor"}},
        {"$lookup": {"from": "survey_tasks", "localField": "_id", "foreignField": "assigned_surveyor_id", "as": "tasks"}},
        {"$project": {"staff_code": 1, "name": 1, "workload": 1, "task_count": {"$size": "$tasks"}, "completed": {"$size": {"$filter": {"input": "$tasks", "as": "t", "cond": {"$eq": ["$$t.status", "registrar_reviewed"]}}}}}},
        {"$sort": {"task_count": -1}},
    ]
    return clean(list(db().staff_members.aggregate(pipeline)))


@router.get("/analytics/registrars")
def registrar_analytics(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    pipeline = [
        {"$match": {"registrar_review.registrar_id": {"$exists": True}}},
        {"$group": {"_id": "$registrar_review.registrar_id", "reviews": {"$sum": 1}, "approved": {"$sum": {"$cond": [{"$in": ["$registrar_review.decision", ["accepted", "approved_for_certificate"]]}, 1, 0]}}}},
        {"$sort": {"reviews": -1}},
    ]
    return clean(list(db().land_applications.aggregate(pipeline)))


@router.get("/analytics/geofeeds/parcels")
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


@router.get("/analytics/geofeeds/pending-heatmap")
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


@router.get("/reports/applications.csv")
def applications_csv(user: dict[str, Any] = Depends(require_staff)) -> StreamingResponse:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["application_id", "type", "status", "zone", "parcel_number", "submitted_at"])
    for row in db().land_applications.find({}).sort("timestamps.submitted_at", DESCENDING):
        writer.writerow([row.get("application_id"), row.get("application_type"), row.get("status"), row.get("parcel_ref", {}).get("zone_id"), row.get("parcel_ref", {}).get("parcel_number"), row.get("timestamps", {}).get("submitted_at")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=lrmis_applications.csv"})
