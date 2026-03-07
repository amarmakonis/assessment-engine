#!/usr/bin/env python3
"""
Delete all uploaded scripts, scripts, evaluations, OCR results, and GridFS files.
Keeps exams and users. Run from project root: python backend/scripts/clear_uploads_and_scripts.py
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import get_settings
from pymongo import MongoClient


def main():
    settings = get_settings()
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]

    # Delete collections (all docs) — keep exams and users
    for name in ["uploaded_scripts", "scripts", "evaluation_results", "ocr_page_results"]:
        if name in db.list_collection_names():
            result = db[name].delete_many({})
            print(f"Deleted {result.deleted_count} document(s) from {name}.")

    # Clear GridFS (uploaded answer scripts / files)
    for coll_name in ["fs.files", "fs.chunks"]:
        if coll_name in db.list_collection_names():
            result = db[coll_name].delete_many({})
            print(f"Deleted {result.deleted_count} from {coll_name}.")

    client.close()
    print("Done. Exams and users were kept.")


if __name__ == "__main__":
    main()
