from sqlalchemy import Column, Integer, String, DateTime, JSON, Index
from sqlalchemy.sql import func

from app.database import Base


class WebIntelligenceCache(Base):
    __tablename__ = "web_intelligence_cache"

    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String, nullable=False)

    # The entity being monitored, e.g. a company domain or name.
    # Used as the lookup key when the agent asks "what's the current G2 score for X?"
    target_entity = Column(String, nullable=False)

    # Raw scraped payload: {"rating": 4.4, "review_count": 312, "themes": [...], ...}
    scraped_data = Column(JSON, nullable=True)

    scraped_at = Column(DateTime(timezone=True), nullable=False)

    # Cache TTL: 6 hours as specified. Query filters expires_at > now() to skip stale rows.
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Composite index for the primary cache-lookup query:
        # WHERE target_entity = ? AND expires_at > now()
        Index("ix_web_intel_entity_expires", "target_entity", "expires_at"),
    )
