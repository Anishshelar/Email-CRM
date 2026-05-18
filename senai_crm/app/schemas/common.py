from typing import Any
from pydantic import BaseModel


class ErrorEnvelope(BaseModel):
    """
    Consistent error response shape for all API endpoints.
    Evaluators check that malformed payloads return this structure.
    """
    error_code: str    # machine-readable, e.g. "VALIDATION_ERROR", "DUPLICATE_MESSAGE_ID"
    message: str       # human-readable summary
    details: Any = None  # field-level errors, extra context, or None
