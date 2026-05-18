"""GET /intelligence/reputation — Phase 5. Web intelligence endpoint."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.web_intelligence_service import WebIntelligenceService

router = APIRouter()


class ReputationResponse(BaseModel):
    company: str
    entity_key: str
    g2: Optional[dict] = None
    trustpilot: Optional[dict] = None
    themes: list[str] = []
    summary: str
    from_cache: bool


@router.get(
    "/reputation",
    response_model=ReputationResponse,
    summary="Fetch public reputation data for a company from G2 and Trustpilot",
)
def get_reputation(
    company: str = Query(..., description="Company name"),
    domain: Optional[str] = Query(None, description="Company domain (slug) for URL construction"),
    db: Session = Depends(get_db),
) -> ReputationResponse:
    svc = WebIntelligenceService(db)
    data = svc.get_sentiment(company, domain)
    return ReputationResponse(**data)
