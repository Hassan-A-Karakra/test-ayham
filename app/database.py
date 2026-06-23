import os
from functools import lru_cache

from dotenv import load_dotenv
from pymongo import ASCENDING, GEOSPHERE, MongoClient

load_dotenv()


@lru_cache
def get_client() -> MongoClient:
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def get_db():
    return get_client()[os.getenv("MONGO_DB", "lrmis")]


def ensure_indexes() -> None:
    db = get_db()
    db.land_applications.create_index("application_id", unique=True)
    db.land_applications.create_index("idempotency_key", unique=True, sparse=True)
    db.land_applications.create_index("status")
    db.land_applications.create_index("application_type")
    db.land_applications.create_index("parcel_ref.parcel_number")
    db.land_applications.create_index("parcel_ref.zone_id")
    db.land_applications.create_index("timestamps.submitted_at")
    db.parcels.create_index("parcel_code", unique=True)
    db.parcels.create_index([("geometry", GEOSPHERE)])
    db.parcels.create_index("zone_id")
    db.applicants.create_index("identity.national_id", unique=True)
    db.staff_members.create_index("staff_code", unique=True)
    db.staff_members.create_index([("role", ASCENDING), ("coverage.zone_ids", ASCENDING)])
    db.survey_tasks.create_index("application_id")
    db.certificates.create_index("certificate_id", unique=True)
