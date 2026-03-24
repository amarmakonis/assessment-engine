import os
from datetime import datetime, timezone

import bcrypt
from dotenv import load_dotenv

from db import get_collection, get_db, using_mock_db

load_dotenv()

APP_COLLECTIONS = [
    "users",
    "exams",
    "scripts",
    "uploaded_scripts",
    "ocr_page_results",
    "evaluation_results",
    "exam_jobs",
    "fs.files",
    "fs.chunks",
]


def _now():
    return datetime.now(timezone.utc)


def clear_app_collections():
    db = get_db()
    for name in APP_COLLECTIONS:
        db[name].delete_many({})


def ensure_indexes():
    get_collection("users").create_index("email", unique=True)
    get_collection("users").create_index("institutionId")
    get_collection("exams").create_index([("institutionId", 1), ("createdAt", -1)])
    get_collection("uploaded_scripts").create_index([("institutionId", 1), ("createdAt", -1)])
    get_collection("uploaded_scripts").create_index([("examId", 1), ("createdAt", -1)])


def seed_admin_user():
    email = os.getenv("SEED_ADMIN_EMAIL", "admin@makonis.ai")
    password = os.getenv("SEED_ADMIN_PASSWORD", "Admin@12345")
    institution_id = os.getenv("SEED_INSTITUTION_ID", "inst_001")

    users = get_collection("users")
    if users.find_one({"email": email}):
        return {"email": email, "password": password, "institutionId": institution_id, "created": False}

    users.insert_one(
        {
            "email": email,
            "passwordHash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            "fullName": "Institution Admin",
            "institutionId": institution_id,
            "role": "INSTITUTION_ADMIN",
            "isActive": True,
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    return {"email": email, "password": password, "institutionId": institution_id, "created": True}


if __name__ == "__main__":
    clear_app_collections()
    ensure_indexes()
    seeded = seed_admin_user()
    print(
        {
            "mockDatabase": using_mock_db(),
            "collectionsCleared": APP_COLLECTIONS,
            "seedAdmin": seeded,
        }
    )
