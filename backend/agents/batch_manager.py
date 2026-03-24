import uuid
import zipfile
import io
import os
import json
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from bson import ObjectId
from db import get_collection

logger = logging.getLogger(__name__)

class BatchManager:
    _executor = ThreadPoolExecutor(max_workers=int(os.getenv("BATCH_MAX_WORKERS", "4")))

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    @classmethod
    def create_job(cls, job_type, institution_id, created_by, total_files=0):
        job_id = str(uuid.uuid4())
        job_doc = {
            "id": job_id,
            "type": job_type,
            "status": "PENDING",
            "institutionId": institution_id,
            "createdBy": created_by,
            "totalFiles": total_files,
            "processedFiles": 0,
            "failedFiles": 0,
            "results": [],
            "createdAt": cls._now(),
            "updatedAt": cls._now()
        }
        get_collection("jobs").insert_one(job_doc)
        return job_id

    @classmethod
    def update_job_progress(cls, job_id, result=None, increment_processed=True, is_failed=False):
        update_data = {
            "updatedAt": cls._now(),
            "status": "RUNNING"
        }
        
        push_data = {}
        if result:
            push_data["results"] = result
            
        inc_data = {}
        if increment_processed:
            inc_data["processedFiles"] = 1
        if is_failed:
            inc_data["failedFiles"] = 1

        update_op = {"$set": update_data}
        if push_data:
            update_op["$push"] = push_data
        if inc_data:
            update_op["$inc"] = inc_data

        get_collection("jobs").update_one({"id": job_id}, update_op)
        
        # Check if completed
        job = get_collection("jobs").find_one({"id": job_id})
        if job and job["processedFiles"] >= job["totalFiles"]:
            get_collection("jobs").update_one(
                {"id": job_id}, 
                {"$set": {"status": "COMPLETED", "updatedAt": cls._now()}}
            )

    @classmethod
    def submit_exam_batch(cls, job_id, zip_bytes, institution_id, created_by, process_fn):
        cls._executor.submit(cls._run_exam_batch, job_id, zip_bytes, institution_id, created_by, process_fn)

    @classmethod
    def _run_exam_batch(cls, job_id, zip_bytes, institution_id, created_by, process_fn):
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                # Filter for valid files (PDFs and Images)
                filenames = [f for f in z.namelist() if f.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')) and not f.startswith('__MACOSX')]
                
                get_collection("jobs").update_one(
                    {"id": job_id}, 
                    {"$set": {"totalFiles": len(filenames), "status": "RUNNING"}}
                )

                if not filenames:
                    get_collection("jobs").update_one(
                        {"id": job_id}, 
                        {"$set": {"status": "COMPLETED", "updatedAt": cls._now()}}
                    )
                    return

                for filename in filenames:
                    try:
                        file_data = z.read(filename)
                        # Call the processing function provided by app.py
                        result = process_fn(file_data, filename, institution_id, created_by)
                        cls.update_job_progress(job_id, {
                            "filename": filename,
                            "status": "SUCCESS",
                            "entityId": result.get("entityId") or result.get("id") or result.get("examId")
                        })
                    except Exception as e:
                        logger.error(f"Error processing {filename} in batch {job_id}: {str(e)}")
                        cls.update_job_progress(job_id, {
                            "filename": filename,
                            "status": "FAILED",
                            "error": str(e)
                        }, is_failed=True)

        except Exception as e:
            logger.error(f"Batch {job_id} critical failure: {str(e)}")
            get_collection("jobs").update_one(
                {"id": job_id}, 
                {"$set": {"status": "FAILED", "updatedAt": cls._now(), "error": str(e)}}
            )

    @classmethod
    def submit_script_batch(cls, job_id, zip_bytes, exam_id, institution_id, created_by, process_fn):
        cls._executor.submit(cls._run_script_batch, job_id, zip_bytes, exam_id, institution_id, created_by, process_fn)

    @classmethod
    def _run_script_batch(cls, job_id, zip_bytes, exam_id, institution_id, created_by, process_fn):
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                filenames = [f for f in z.namelist() if f.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')) and not f.startswith('__MACOSX')]
                
                get_collection("jobs").update_one(
                    {"id": job_id}, 
                    {"$set": {"totalFiles": len(filenames), "status": "RUNNING"}}
                )

                if not filenames:
                    get_collection("jobs").update_one(
                        {"id": job_id}, 
                        {"$set": {"status": "COMPLETED", "updatedAt": cls._now()}}
                    )
                    return

                for filename in filenames:
                    try:
                        file_data = z.read(filename)
                        result = process_fn(file_data, filename, exam_id, institution_id, created_by)
                        cls.update_job_progress(job_id, {
                            "filename": filename,
                            "status": "SUCCESS",
                            "entityId": result.get("entityId") or result.get("id") or result.get("scriptId")
                        })
                    except Exception as e:
                        logger.error(f"Error processing {filename} in batch {job_id}: {str(e)}")
                        cls.update_job_progress(job_id, {
                            "filename": filename,
                            "status": "FAILED",
                            "error": str(e)
                        }, is_failed=True)

        except Exception as e:
            logger.error(f"Batch {job_id} critical failure: {str(e)}")
            get_collection("jobs").update_one(
                {"id": job_id}, 
                {"$set": {"status": "FAILED", "updatedAt": cls._now(), "error": str(e)}}
            )
