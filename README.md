# LRMIS - Land Registration Management Information System

COMP4382 final project implementing a secure, workflow-driven, geo-enabled Land Registration Management Information System using **FastAPI**, **MongoDB with PyMongo**, and **React**.

LRMIS is not a simple CRUD application. It manages land registration applications, parcel GeoJSON data, applicant profiles, required documents, objections, field survey tasks, registrar review, certificate issuance, audit logs, analytics, and a live map.

## Project Goal

Improve land registration transparency, efficiency, accuracy, and accountability through a digital Management Information System that supports:

- Land applications from citizens, lawyers, companies, surveyors, and authorized representatives.
- Parcel management with GeoJSON boundaries and MongoDB geospatial indexes.
- Applicant, parcel, ownership document, and evidence validation.
- Strict workflow transitions from submission to closure.
- Field survey assignment based on zone, workload, availability-ready data, and skills.
- Objections, missing documents, registrar decisions, and internal notes.
- Official certificate metadata generation.
- Dashboards, spatial maps, analytics, and CSV management reports.

## Technology Stack

- **Backend:** FastAPI, PyMongo, Pydantic, Uvicorn, python-dotenv
- **Database:** MongoDB local, MongoDB Atlas, or MongoDB Compass
- **Frontend:** React, Vite, Leaflet, OpenStreetMap, lucide-react
- **Documentation:** Swagger/OpenAPI and Postman collection
- **Authentication:** Simple signed bearer token demo authentication

## Implemented Modules

| Requirement Module | Implementation |
| --- | --- |
| Student 1 - Land Application Management | `app/modules/land_applications.py` |
| Student 2 - Applicant Portal and Profiles | `app/modules/applicant_portal.py` |
| Student 3 - Surveyors, Registrar, and Assignment | `app/modules/surveyor_registrar.py` |
| Group Module - Data Analysis, Map, and Visualization | `app/modules/analytics_map.py` |
| Authentication | `app/modules/auth.py`, `app/security.py` |
| Frontend UI | `frontend/src/main.jsx`, `frontend/src/styles.css` |

## Core Features

### Land Application Management

- Create land registration applications with idempotency key support.
- Validate application type, applicant reference, parcel details, documents, and GeoJSON polygon data.
- Support application types:
  - `first_registration`
  - `ownership_transfer`
  - `parcel_subdivision`
  - `parcel_merge`
  - `boundary_correction`
  - `certificate_request`
- List applications with pagination, filtering, and sorting.
- Retrieve full application details with parcel, audit log, certificate, and survey task data.
- Enforce workflow transitions and mandatory transition rules.
- Place applications on hold or reject them with required reasons.
- Generate certificate metadata after approval.

### Applicant Portal

- Create applicant profiles.
- Support applicant types:
  - `citizen`
  - `lawyer`
  - `company`
  - `surveyor`
  - `authorized_representative`
- Store identity, contact details, address, verification state, preferred language, notification preferences, privacy settings, and linked applications.
- Allow applicants to upload document metadata, add comments, submit objections, and view application timelines.

### Surveyor and Registrar Module

- Create staff profiles for surveyors, registrars, managers, and clerks.
- Store coverage zones, skills, schedules, workload, contacts, and active state.
- Automatically assign survey tasks using zone, workload, and skill matching.
- Track survey milestones:
  - `assigned`
  - `visit_scheduled`
  - `arrived_on_site`
  - `survey_started`
  - `survey_completed`
  - `report_uploaded`
  - `registrar_reviewed`
- Upload survey report metadata and evidence.
- Save registrar decisions and internal notes.

### Analytics, Map, and Reports

- KPI endpoint for total, pending, approved, rejected, objection, certificate, and average processing metrics.
- Aggregations by application status, zone, processing time, surveyor workload, and registrar workload.
- GeoJSON feeds for parcel display and pending heatmap data.
- CSV export for application reports.
- React + Leaflet + OpenStreetMap frontend map.

## Workflow

Main workflow:

```text
submitted -> pre_checked -> survey_required -> surveyed -> legal_review -> approved -> certificate_issued -> closed
```

Alternative states:

```text
rejected, on_hold, missing_documents, under_objection
```

Required workflow rules implemented in the backend:

- An application cannot move to `pre_checked` unless applicant and parcel information are complete.
- An application cannot move to `survey_required` unless the parcel location is valid.
- An application cannot move to `surveyed` unless a survey report exists.
- An application cannot move to `legal_review` unless an ownership document is uploaded, pending review, or verified.
- An application cannot move to `approved` unless registrar review is accepted or approved for certificate.
- A certificate cannot be issued unless the application is approved.
- Rejected applications must include a rejection reason.
- Applications with objections move to `under_objection`.

## Project Structure

```text
app/
  core.py                    Shared database helpers, IDs, workflow, serialization
  database.py                MongoDB connection and index creation
  main.py                    FastAPI app setup, routers, CORS, frontend serving
  schemas.py                 Pydantic request validation models
  security.py                Simple signed token authentication
  modules/
    auth.py                  Login and current-user endpoints
    land_applications.py     Land application workflow and certificates
    applicant_portal.py      Applicant profiles, documents, comments, objections
    surveyor_registrar.py    Staff, survey assignment, reports, registrar review
    analytics_map.py         KPIs, map feeds, analytics, CSV export
frontend/
  src/
    main.jsx                 React screens and API integration
    styles.css               Frontend styling
  index.html                 Vite entrypoint
  package.json               Frontend dependencies and scripts
postman/
  LRMIS.postman_collection.json
requirements.txt
.env.example
README.md
```

## Setup

1. Install MongoDB locally or prepare a MongoDB Atlas connection string.

2. Create `.env` from `.env.example`:

```bash
MONGO_URI=mongodb://localhost:27017
MONGO_DB=lrmis
APP_SECRET=change-this-secret
CREATE_INDEXES=true
```

3. Install backend packages:

```bash
python -m pip install -r requirements.txt
```

4. Install and build the frontend:

```bash
cd frontend
npm install
npm run build
cd ..
```

5. Run the FastAPI server:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

6. Open the application:

```text
http://127.0.0.1:8000
```

Swagger/OpenAPI documentation:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
http://127.0.0.1:8000/health
```

## Frontend Development

For frontend-only development, run the backend on port `8000`, then run:

```bash
cd frontend
npm run dev
```

Vite runs on:

```text
http://127.0.0.1:5173
```

The production React build is served by FastAPI from `frontend/dist`.

## Demo Users

These are authentication users only. They are not MongoDB seed records.

| Username | Password | Role |
| --- | --- | --- |
| applicant | applicant123 | applicant |
| staff | staff123 | staff |
| surveyor | surveyor123 | surveyor |
| manager | manager123 | manager |

## Main API Endpoints

### Authentication

- `POST /auth/login`
- `GET /auth/me`

### Land Applications

- `POST /applications/`
- `GET /applications/`
- `GET /applications/{application_id}`
- `PATCH /applications/{application_id}/transition`
- `POST /applications/{application_id}/hold`
- `POST /applications/{application_id}/reject`
- `POST /applications/{application_id}/certificate`

### Applicant Portal

- `POST /applicants/`
- `GET /applicants/{applicant_id}`
- `GET /applicants/{applicant_id}/applications`
- `POST /applications/{application_id}/documents`
- `POST /applications/{application_id}/comments`
- `POST /applications/{application_id}/objections`
- `GET /applications/{application_id}/timeline`

### Surveyor and Registrar

- `POST /staff/`
- `GET /staff/{staff_id}`
- `POST /applications/{application_id}/auto-assign-surveyor`
- `PATCH /applications/{application_id}/survey-milestone`
- `POST /applications/{application_id}/survey-report`
- `PATCH /applications/{application_id}/registrar-review`

### Analytics, Map, and Reports

- `GET /analytics/kpis`
- `GET /analytics/applications-by-status`
- `GET /analytics/applications-by-zone`
- `GET /analytics/processing-time`
- `GET /analytics/surveyors`
- `GET /analytics/registrars`
- `GET /analytics/geofeeds/parcels`
- `GET /analytics/geofeeds/pending-heatmap`
- `GET /reports/applications.csv`

## MongoDB Collections

The project uses these main collections:

- `land_applications`
- `parcels`
- `applicants`
- `application_documents`
- `objections`
- `staff_members`
- `survey_tasks`
- `survey_reports`
- `performance_logs`
- `certificates`

## MongoDB Indexes

Indexes are created on startup when `CREATE_INDEXES=true`:

```python
db.land_applications.create_index("application_id", unique=True)
db.land_applications.create_index("idempotency_key", unique=True, sparse=True)
db.land_applications.create_index("status")
db.land_applications.create_index("application_type")
db.land_applications.create_index("parcel_ref.parcel_number")
db.land_applications.create_index("parcel_ref.zone_id")
db.land_applications.create_index("timestamps.submitted_at")

db.parcels.create_index("parcel_code", unique=True)
db.parcels.create_index([("geometry", "2dsphere")])
db.parcels.create_index("zone_id")

db.applicants.create_index("identity.national_id", unique=True)
db.staff_members.create_index("staff_code", unique=True)
db.staff_members.create_index([("role", 1), ("coverage.zone_ids", 1)])
db.survey_tasks.create_index("application_id")
db.certificates.create_index("certificate_id", unique=True)
```

## Example Demo Flow

1. Login with `POST /auth/login`.
2. Create an applicant with `POST /applicants/`.
3. Create a land application with `POST /applications/` and an `Idempotency-Key` header.
4. Create at least one surveyor using `POST /staff/`.
5. Move the application to `pre_checked`.
6. Move the application to `survey_required`.
7. Auto-assign a surveyor.
8. Add survey milestones.
9. Upload a survey report.
10. Move the application to `surveyed`.
11. Move the application to `legal_review`.
12. Save registrar review.
13. Move the application to `approved`.
14. Issue a certificate.
15. Move the application to `closed`.
16. View analytics, map feeds, timeline, and CSV report.

## Important Notes

- The backend uses **PyMongo only**.
- The application does not automatically seed sample applicants, parcels, staff, applications, or certificates.
- Create applicant and staff records through the UI or API before running the full workflow.
- To auto-assign a surveyor, create a staff member with role `surveyor` and matching `coverage.zone_ids`.
- To move an application to `surveyed`, upload a survey report first.
- To move an application to `approved`, save a registrar review with decision `accepted` or `approved_for_certificate`.
- To issue a certificate, the application must be in `approved` status.
- GeoJSON parcel polygons must be valid closed polygons using `[longitude, latitude]` coordinate pairs.

## Project Deliverables Coverage

- Working FastAPI backend.
- MongoDB integration using PyMongo.
- Pydantic validation models.
- Workflow transitions and validation rules.
- Automatic surveyor assignment.
- Applicant portal.
- Staff console.
- Surveyor interface.
- Registrar review interface.
- Analytics dashboard.
- Interactive map using OpenStreetMap and Leaflet.
- README setup instructions, packages, environment variables, indexes, users, and run instructions.
- Swagger/OpenAPI documentation.
- Postman collection in `postman/LRMIS.postman_collection.json`.
- Example API flow for demo and discussion.

## Presentation Outline

- Project problem and LRMIS goal.
- System architecture: FastAPI, PyMongo, MongoDB, React, Leaflet.
- Database collections and indexes.
- Workflow state machine and validation rules.
- Applicant portal demo.
- Staff and registrar console demo.
- Survey assignment and surveyor flow demo.
- Map and analytics demo.
- Certificate issuance demo.
- Design decisions, challenges, and future improvements.
