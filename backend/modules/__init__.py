"""Shared helpers for KnowSuite modules."""
import hashlib
import math
from datetime import datetime

from fastapi import Header, HTTPException

import config


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


def month_key(dt=None):
    return (dt or datetime.utcnow()).strftime("%Y-%m")


def require_admin(x_admin_token: str = Header(default="")):
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="管理员口令错误（X-Admin-Token）")
    return True


def excerpt(text, limit=5000):
    return (text or "")[:limit]
