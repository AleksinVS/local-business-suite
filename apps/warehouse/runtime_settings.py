"""Read warehouse settings through the central document repository."""

from __future__ import annotations

import copy
from typing import Any

from apps.settings_center.document_repository import get_document
from .contracts import validate_warehouse_settings_payload


WAREHOUSE_SETTINGS_DOCUMENT_ID = "warehouse.settings"


def get_warehouse_runtime_settings(request=None) -> dict[str, Any]:
    """Return a validated copy of one request-local repository snapshot."""
    snapshot = get_document(WAREHOUSE_SETTINGS_DOCUMENT_ID, request=request)
    return copy.deepcopy(validate_warehouse_settings_payload(snapshot.payload))
