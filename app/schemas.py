from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ApplicationType(str, Enum):
    first_registration = "first_registration"
    ownership_transfer = "ownership_transfer"
    parcel_subdivision = "parcel_subdivision"
    parcel_merge = "parcel_merge"
    boundary_correction = "boundary_correction"
    certificate_request = "certificate_request"


class ApplicationStatus(str, Enum):
    submitted = "submitted"
    pre_checked = "pre_checked"
    survey_required = "survey_required"
    surveyed = "surveyed"
    legal_review = "legal_review"
    approved = "approved"
    certificate_issued = "certificate_issued"
    closed = "closed"
    rejected = "rejected"
    on_hold = "on_hold"
    missing_documents = "missing_documents"
    under_objection = "under_objection"


class GeoJsonPolygon(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]

    @field_validator("coordinates")
    @classmethod
    def validate_polygon(cls, value: list[list[list[float]]]) -> list[list[list[float]]]:
        if not value or not value[0] or len(value[0]) < 4:
            raise ValueError("Polygon must contain at least four coordinate pairs")
        if value[0][0] != value[0][-1]:
            raise ValueError("Polygon ring must be closed")
        for ring in value:
            for point in ring:
                if len(point) != 2:
                    raise ValueError("Each coordinate must be [longitude, latitude]")
                lon, lat = point
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise ValueError("Invalid longitude or latitude")
        return value


class ContactInfo(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None


class ApplicantIdentity(BaseModel):
    national_id: str = Field(min_length=4)
    verified: bool = False
    verification_method: str | None = None
    verified_at: datetime | None = None


class ApplicantCreate(BaseModel):
    full_name: str = Field(min_length=2)
    applicant_type: Literal["citizen", "lawyer", "company", "surveyor", "authorized_representative"]
    identity: ApplicantIdentity
    contacts: ContactInfo
    address: dict[str, Any]
    verification_state: Literal["unverified", "verified", "suspended"] = "unverified"
    preferred_language: Literal["ar", "en"] = "ar"
    notification_preferences: dict[str, bool] = Field(default_factory=dict)
    privacy_settings: dict[str, Any] = Field(default_factory=dict)


class ParcelInput(BaseModel):
    parcel_number: str = Field(min_length=1)
    block_number: str = Field(min_length=1)
    basin_number: str = Field(min_length=1)
    zone_id: str = Field(min_length=2)
    area_sqm: float | None = Field(default=None, gt=0)
    land_use: str | None = None
    geometry: GeoJsonPolygon


class ApplicantRef(BaseModel):
    applicant_id: str
    applicant_type: str
    submitted_by_representative: bool = False


class DocumentInput(BaseModel):
    document_type: str = Field(min_length=2)
    file_name: str | None = None
    file_url: str | None = None
    required: bool = True
    status: Literal["missing", "uploaded", "pending_review", "verified", "rejected"] = "uploaded"
    notes: str | None = None


class ApplicationCreate(BaseModel):
    application_type: ApplicationType
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    applicant_ref: ApplicantRef
    parcel: ParcelInput
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    required_documents: list[DocumentInput] = Field(default_factory=list)


class TransitionRequest(BaseModel):
    target_state: ApplicationStatus
    actor_type: str = "staff"
    actor_id: str = "system"
    notes: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class HoldRequest(BaseModel):
    reason: str = Field(min_length=3)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=3)


class CommentCreate(BaseModel):
    author_type: Literal["applicant", "staff", "surveyor", "registrar"]
    author_id: str
    message: str = Field(min_length=1)


class ObjectionCreate(BaseModel):
    submitted_by: str
    reason: str = Field(min_length=5)
    supporting_documents: list[DocumentInput] = Field(default_factory=list)


class StaffCreate(BaseModel):
    staff_code: str = Field(min_length=2)
    name: str = Field(min_length=2)
    role: Literal["surveyor", "registrar", "manager", "clerk"]
    department: str
    skills: list[str] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    schedule: dict[str, Any] = Field(default_factory=dict)
    workload: dict[str, int] = Field(default_factory=lambda: {"active_tasks": 0, "max_tasks": 10})
    contacts: ContactInfo = Field(default_factory=ContactInfo)
    active: bool = True


class SurveyMilestoneRequest(BaseModel):
    milestone: Literal[
        "assigned",
        "visit_scheduled",
        "arrived_on_site",
        "survey_started",
        "survey_completed",
        "report_uploaded",
        "registrar_reviewed",
    ]
    by: str
    meta: dict[str, Any] = Field(default_factory=dict)


class SurveyReportCreate(BaseModel):
    report_number: str = Field(min_length=2)
    file_name: str | None = None
    file_url: str | None = None
    summary: str
    measurements: dict[str, Any] = Field(default_factory=dict)
    evidence: list[DocumentInput] = Field(default_factory=list)


class RegistrarReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected", "needs_changes", "approved_for_certificate"]
    registrar_id: str
    notes: str = Field(min_length=2)


class LoginRequest(BaseModel):
    username: str
    password: str


class PublicModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
