from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request


def jwt_required(fn=None, *, roles=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                verify_jwt_in_request()
            except Exception as exc:
                return jsonify({"message": str(exc)}), 401

            claims = get_jwt()
            g.current_user_id = get_jwt_identity()
            g.institution_id = claims.get("institution_id")
            g.user_role = claims.get("role")

            if roles and g.user_role not in roles:
                return jsonify({"message": "Forbidden"}), 403
            return func(*args, **kwargs)

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def get_current_user_id():
    try:
        return getattr(g, "current_user_id", None)
    except RuntimeError:
        return None


def get_current_institution_id():
    try:
        return getattr(g, "institution_id", None)
    except RuntimeError:
        return None
