#!/usr/bin/env python3
"""Clear all exams from the database. Run from project root: python backend/scripts/clear_exams.py"""

import sys
from pathlib import Path

# Add backend to path and load config from project root .env
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import get_settings
from pymongo import MongoClient

def main():
    settings = get_settings()
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]
    result = db.exams.delete_many({})
    print(f"Deleted {result.deleted_count} exam(s) from database.")
    client.close()

if __name__ == "__main__":
    main()
