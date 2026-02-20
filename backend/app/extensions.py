"""
Flask extension singletons — initialized once, bound to app in the factory.
"""

from __future__ import annotations

import redis
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_smorest import Api
from pymongo import MongoClient
from prometheus_client import CollectorRegistry

cors = CORS()
jwt = JWTManager()
smorest_api = Api()

_mongo_client: MongoClient | None = None
_redis_client: redis.Redis | None = None
_prom_registry = CollectorRegistry(auto_describe=True)


def init_mongo(uri: str, **kwargs) -> MongoClient:
    global _mongo_client
    _mongo_client = MongoClient(uri, **kwargs)
    return _mongo_client


def get_mongo() -> MongoClient:
    if _mongo_client is None:
        raise RuntimeError("MongoDB client not initialized — call init_mongo first")
    return _mongo_client


def init_redis(url: str) -> redis.Redis:
    global _redis_client
    _redis_client = redis.Redis.from_url(url, decode_responses=True)
    return _redis_client


def get_redis() -> redis.Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized — call init_redis first")
    return _redis_client


def get_prom_registry() -> CollectorRegistry:
    return _prom_registry
