# LRMIS - Land Registration Management Information System

FastAPI + MongoDB + React project for COMP4382 Land Registration final project. The backend uses **PyMongo only**. It does not use Motor and does not generate or seed database records in code.

## Features

- React login page with simple token authentication.
- Applicant profiles and applicant portal actions.
- Land application CRUD with pagination, filters, sorting, idempotency key support, GeoJSON parcels, document metadata, notes, objections, and audit timeline.
- Strict workflow transitions:
  `submitted -> pre_checked -> survey_required -> surveyed -> legal_review -> approved -> certificate_issued -> closed`
- Alternative states: `rejected`, `on_hold`, `missing_documents`, `under_objection`.
- Surveyor/staff management, automatic survey assignment by zone, workload, availability-ready fields, and skills.
- Survey milestones and survey report metadata.
- Registrar review and certificate metadata issuance.
- Analytics KPIs, status/zone aggregations, surveyor/registrar workload, processing time.
- React + Leaflet + OpenStreetMap live parcel map using GeoJSON.
- CSV export endpoint.
- Swagger/OpenAPI docs and Postman collection.

## Project Structure

```text
app/
  database.py      MongoDB client and indexes
  main.py          FastAPI routes and workflow logic
  schemas.py       Pydantic validation models
  security.py      Simple signed token login
frontend/
  src/             React UI source
  index.html       Vite entrypoint
  package.json     React/Vite dependencies and scripts
  dist/            Production build served by FastAPI after npm run build
postman/
  LRMIS.postman_collection.json
requirements.txt
.env.example
```

## Setup

1. Install MongoDB locally or use MongoDB Atlas.
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

4. Install and build the React frontend:

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

6. Open:

```text
http://127.0.0.1:8000
```

Swagger docs:

```text
http://127.0.0.1:8000/docs
```

## Demo Users

These are authentication users only. They are not database seed records.

| Username | Password | Role |
| --- | --- | --- |
| applicant | applicant123 | applicant |
| staff | staff123 | staff |
| surveyor | surveyor123 | surveyor |
| manager | manager123 | manager |

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
db.survey_tasks.create_index("application_id")
db.certificates.create_index("certificate_id", unique=True)
```

## Important Notes

- The app does not create sample applicants, staff, applications, or parcels automatically.
- The React production build is served from `frontend/dist` by FastAPI.
- For frontend development only, run `npm run dev` inside `frontend`; Vite proxies API requests to `http://127.0.0.1:8000`.
- Use the UI or API to create applicant/staff records first.
- To auto-assign a surveyor, create at least one staff member with role `surveyor` and a matching `coverage.zone_ids` value.
- To move an application to `surveyed`, upload a survey report first.
- To move an application to `approved`, save a registrar review with `accepted` or `approved_for_certificate`.
- To issue a certificate, the application must be `approved`.

## Example API Flow

1. `POST /auth/login`
2. `POST /applicants/`
3. `POST /applications/` with `Idempotency-Key`
4. `POST /staff/` to create a surveyor
5. `PATCH /applications/{id}/transition` to `pre_checked`
6. `PATCH /applications/{id}/transition` to `survey_required`
7. `POST /applications/{id}/auto-assign-surveyor`
8. `POST /applications/{id}/survey-report`
9. `PATCH /applications/{id}/transition` to `surveyed`
10. `PATCH /applications/{id}/transition` to `legal_review`
11. `PATCH /applications/{id}/registrar-review`
12. `PATCH /applications/{id}/transition` to `approved`
13. `POST /applications/{id}/certificate`

## Main Endpoints

- `POST /applications/`
- `GET /applications/`
- `GET /applications/{application_id}`
- `PATCH /applications/{application_id}/transition`
- `POST /applications/{application_id}/hold`
- `POST /applications/{application_id}/reject`
- `POST /applications/{application_id}/certificate`
- `POST /applicants/`
- `GET /applicants/{applicant_id}`
- `GET /applicants/{applicant_id}/applications`
- `POST /applications/{application_id}/documents`
- `POST /applications/{application_id}/comments`
- `POST /applications/{application_id}/objections`
- `GET /applications/{application_id}/timeline`
- `POST /staff/`
- `GET /staff/{staff_id}`
- `POST /applications/{application_id}/auto-assign-surveyor`
- `PATCH /applications/{application_id}/survey-milestone`
- `POST /applications/{application_id}/survey-report`
- `PATCH /applications/{application_id}/registrar-review`
- `GET /analytics/kpis`
- `GET /analytics/applications-by-status`
- `GET /analytics/applications-by-zone`
- `GET /analytics/processing-time`
- `GET /analytics/surveyors`
- `GET /analytics/registrars`
- `GET /analytics/geofeeds/parcels`
- `GET /analytics/geofeeds/pending-heatmap`
- `GET /reports/applications.csv`

## Presentation Outline

- Problem and LRMIS goal.
- Architecture: FastAPI, PyMongo, MongoDB collections, static frontend.
- Database design and indexes.
- Workflow state machine and validation rules.
- Applicant portal demo.
- Staff/registrar console demo.
- Survey assignment and surveyor flow demo.
- Map and analytics demo.
- Design decisions, challenges, and future improvements.
