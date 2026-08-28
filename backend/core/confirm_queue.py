"""The one door into the confirm queue.

Every agent that extracts something needs the same rule — below the shop's
threshold, it goes to a human instead of into the books — and was writing the
same document three different ways. One writer means one shape of card for the
UI to render, and one place to change the policy.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core import ids
from core.config import CONFIDENCE_THRESHOLD
from core.firestore_client import db


def is_uncertain(confidence: float | None) -> bool:
    return float(confidence or 0) < CONFIDENCE_THRESHOLD


def enqueue(*, source_type: str, source_id: str, row_id: str, field: str,
            extracted_value, confidence: float,
            alternatives: list | None = None,
            source_image_url: str | None = None,
            crop_bbox: dict | None = None) -> str:
    """Park one uncertain value for the owner. Returns the queue item id."""
    item_id = ids.item_id()
    db().collection("confirm_queue").document(item_id).set({
        "item_id": item_id,
        "source_type": source_type, "source_id": source_id, "row_id": str(row_id),
        "field": field,
        "source_image_url": source_image_url, "crop_bbox": crop_bbox,
        "extracted_value": extracted_value,
        "confidence": round(float(confidence or 0), 2),
        "alternatives": alternatives or [],
        "status": "pending",
        "resolved_value": None, "resolved_at": None, "resolved_by": None,
        "created_at": datetime.now(timezone.utc),
    })
    return item_id
