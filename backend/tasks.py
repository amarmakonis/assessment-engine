import logging
import traceback
import sys
import os

# Ensure the backend directory is in the Python path for Celery workers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from celery_app import celery_app
from datetime import datetime, timezone
from bson import ObjectId
import zipfile
import io
import uuid

# Import processing functions from app.py refactored logic
# Note: We need to be careful with circular imports. 
# Best practice is to have the core logic in a separate module.
from db import get_collection

logger = logging.getLogger(__name__)

def create_notification(user_id, institution_id, message, type="INFO", entity_id=None):
    notifications = get_collection("notifications")
    notifications.insert_one({
        "userId": user_id,
        "institutionId": institution_id,
        "message": message,
        "type": type,
        "entityId": entity_id,
        "read": False,
        "createdAt": datetime.now(timezone.utc)
    })

@celery_app.task(name="tasks.process_exam")
def process_exam_task(job_id, file_bytes, institution_id, created_by, title=None, subject=None, exam_id=None):
    from app import _run_single_exam_processing
    
    logger.info(f"Starting process_exam_task for job {job_id}")
    jobs = get_collection("jobs")
    
    try:
        jobs.update_one({"id": job_id}, {"$set": {"status": "RUNNING", "updatedAt": datetime.now(timezone.utc)}})
        
        # Mocking a filename for the helper
        filename = "uploaded_paper.pdf"
        result = _run_single_exam_processing(file_bytes, filename, institution_id, created_by, title, subject, exam_id=exam_id)
        
        status = "COMPLETED" if result["status"] == "SUCCESS" else "FAILED"
        jobs.update_one({"id": job_id}, {
            "$set": {
                "status": status,
                "processedFiles": 1,
                "results": [result],
                "updatedAt": datetime.now(timezone.utc)
            }
        })
        
        msg = f"Exam creation '{title or 'New Exam'}' done!" if status == "COMPLETED" else f"Exam creation failed for '{title}'"
        create_notification(created_by, institution_id, msg, "SUCCESS" if status == "COMPLETED" else "ERROR", result.get("entityId"))
        
    except Exception as e:
        logger.error(f"Error in process_exam_task: {str(e)}")
        jobs.update_one({"id": job_id}, {
            "$set": {
                "status": "FAILED",
                "error": str(e),
                "updatedAt": datetime.now(timezone.utc)
            }
        })
        create_notification(created_by, institution_id, f"Error processing exam: {str(e)}", "ERROR")

@celery_app.task(name="tasks.process_script")
def process_script_task(job_id, file_bytes, filename, exam_id, institution_id, created_by):
    from app import _run_single_script_processing
    
    logger.info(f"Starting process_script_task for job {job_id}")
    jobs = get_collection("jobs")
    
    try:
        jobs.update_one({"id": job_id}, {"$set": {"status": "RUNNING", "updatedAt": datetime.now(timezone.utc)}})
        
        result = _run_single_script_processing(file_bytes, filename, exam_id, institution_id, created_by)
        
        status = "COMPLETED" if result["status"] == "SUCCESS" else "FAILED"
        jobs.update_one({"id": job_id}, {
            "$set": {
                "status": status,
                "processedFiles": 1,
                "results": [result],
                "updatedAt": datetime.now(timezone.utc)
            }
        })
        
        create_notification(created_by, institution_id, f"Script '{filename}' evaluation done!", "SUCCESS", result.get("entityId"))
        
    except Exception as e:
        logger.error(f"Error in process_script_task: {str(e)}")
        jobs.update_one({"id": job_id}, {"$set": {"status": "FAILED", "error": str(e), "updatedAt": datetime.now(timezone.utc)}})
        create_notification(created_by, institution_id, f"Error evaluating script {filename}: {str(e)}", "ERROR")

@celery_app.task(name="tasks.process_batch")
def process_batch_task(job_id, zip_bytes, institution_id, created_by, type="EXAM", exam_id=None):
    from app import _run_single_exam_processing, _run_single_script_processing
    
    logger.info(f"Starting process_batch_task {job_id} of type {type}")
    jobs = get_collection("jobs")
    
    try:
        jobs.update_one({"id": job_id}, {"$set": {"status": "RUNNING", "updatedAt": datetime.now(timezone.utc)}})
        
        results = []
        processed = 0
        failed = 0
        
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            filenames = [f for f in z.namelist() if not f.startswith("__MACOSX") and (f.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")))]
            
            jobs.update_one({"id": job_id}, {"$set": {"totalFiles": len(filenames)}})
            
            for fname in filenames:
                file_data = z.read(fname)
                try:
                    if type == "EXAM":
                        res = _run_single_exam_processing(file_data, fname, institution_id, created_by)
                    else:
                        res = _run_single_script_processing(file_data, fname, exam_id, institution_id, created_by)
                    
                    results.append(res)
                    if res["status"] == "SUCCESS":
                        processed += 1
                    else:
                        failed += 1
                except Exception as ef:
                    failed += 1
                    results.append({"filename": fname, "status": "FAILED", "error": str(ef)})
                
                # Update progress
                jobs.update_one({"id": job_id}, {
                    "$set": {
                        "processedFiles": processed + failed,
                        "failedFiles": failed,
                        "results": results,
                        "updatedAt": datetime.now(timezone.utc)
                    }
                })
        
        jobs.update_one({"id": job_id}, {"$set": {"status": "COMPLETED", "updatedAt": datetime.now(timezone.utc)}})
        create_notification(created_by, institution_id, f"Batch {type} upload ({processed} success, {failed} failed) is done!", "SUCCESS")
        
    except Exception as e:
        logger.error(f"Error in process_batch_task: {str(e)}")
        jobs.update_one({"id": job_id}, {"$set": {"status": "FAILED", "error": str(e), "updatedAt": datetime.now(timezone.utc)}})
        create_notification(created_by, institution_id, f"Batch process failed: {str(e)}", "ERROR")
