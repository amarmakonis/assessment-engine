import logging
import os

from dotenv import load_dotenv

load_dotenv()

_mongo_client = None
_db = None
_using_mock = False
_logger = logging.getLogger(__name__)


def _allow_mock_fallback():
    configured = os.getenv("ALLOW_MOCK_DB_FALLBACK")
    if configured is not None:
        return configured.lower() == "true"
    return (
        os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes", "on"}
        or os.getenv("FLASK_ENV", "").lower() == "development"
    )


def init_db():
    global _mongo_client, _db, _using_mock
    if _db is not None:
        return _db

    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME", "assessment_engine")
    allow_mock_fallback = _allow_mock_fallback()

    try:
        from pymongo import MongoClient

        timeout_ms = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "10000"))
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=timeout_ms, tz_aware=True)
        client.admin.command("ping")
        _mongo_client = client
        _db = client[db_name]
        _using_mock = False
        return _db
    except Exception as exc:
        if not allow_mock_fallback:
            raise
        import mongomock

        _logger.warning("MongoDB connection failed, using mongomock fallback: %s", exc)
        client = mongomock.MongoClient(tz_aware=True)
        _mongo_client = client
        _db = client[db_name]
        _using_mock = True
        return _db


def get_db():
    return init_db()


def get_collection(name):
    return get_db()[name]


def using_mock_db():
    init_db()
    return _using_mock
