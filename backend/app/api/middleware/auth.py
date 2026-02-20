"""
JWT + RBAC authentication middleware.
"""

from __future__ import annotations

import functools
from typing import Any

from flask import g, request
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from app.common.exceptions import AuthError, ForbiddenError


def jwt_required(fn=None, *, roles: list[str] | None = None):
    """Decorator that enforces JWT auth and optional RBAC role check."""

    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            identity = get_jwt_identity()

            g.current_user_id = identity
            g.institution_id = claims.get("institution_id")
            g.user_role = claims.get("role", "")

            if roles and g.user_role not in roles:
                raise ForbiddenError(
                    f"Role '{g.user_role}' is not authorized. Required: {roles}"
                )
            return f(*args, **kwargs)

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def get_current_institution_id() -> str:
    inst_id = getattr(g, "institution_id", None)
    if not inst_id:
        raise AuthError("Institution context missing from token")
    return inst_id


def get_current_user_id() -> str:
    uid = getattr(g, "current_user_id", None)
    if not uid:
        raise AuthError("User identity missing from token")
    return uid
