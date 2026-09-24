"""GET /api/v1/health - basic application health (section 3.3)."""
from __future__ import annotations

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def get_health():
    return jsonify({"status": "ok"}), 200
