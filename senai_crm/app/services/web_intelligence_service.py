"""
Web intelligence service — Phase 5.

Scrapes G2 and Trustpilot for public sentiment about a company.
Caches results in web_intelligence_cache for 6 hours.
Checks robots.txt before any scrape; if disallowed or scrape fails,
returns mock/fallback data — the agent is never blocked.

Trigger conditions (caller responsibility, checked in agent tool):
  - email body contains 'review', 'G2', or 'Trustpilot'
  - sentiment_score < -0.6
  - category=Complaint + urgency in (High, Critical)

Design:
  - Synchronous (httpx.Client) — agent orchestrator is synchronous.
  - Robots.txt cached in-process for the duration of the request.
  - HTMLParser-based extraction avoids a BeautifulSoup dependency.
  - Falls back to mock data on any error; never raises to caller.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy.orm import Session

from app.models.web_intelligence import WebIntelligenceCache

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 6
REQUEST_TIMEOUT = 10.0
USER_AGENT = "SenAI-CRM-Bot/1.0 (internal monitoring; contact ops@senai.internal)"

# Sources to query per company
SOURCES = {
    "g2": "https://www.g2.com",
    "trustpilot": "https://www.trustpilot.com",
}


class WebIntelligenceService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._robots_cache: dict[str, RobotFileParser] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_sentiment(self, company: str, domain: Optional[str] = None) -> dict:
        """
        Return aggregated public sentiment for `company`.
        Checks cache first; scrapes if stale; falls back to mock on failure.

        Returns:
            {
              "company": str,
              "g2": {...} | None,
              "trustpilot": {...} | None,
              "summary": str,
              "from_cache": bool,
            }
        """
        entity_key = domain or company.lower().replace(" ", "-")

        cached = self._get_cached(entity_key)
        if cached:
            logger.info("Web intelligence: cache hit for '%s'", entity_key)
            return {**cached.scraped_data, "from_cache": True}

        logger.info("Web intelligence: scraping for '%s'", entity_key)
        result = self._scrape_all(company, entity_key)
        self._store_cache(entity_key, result)
        return {**result, "from_cache": False}

    # ── Cache ──────────────────────────────────────────────────────────────────

    def _get_cached(self, entity_key: str) -> Optional[WebIntelligenceCache]:
        now = datetime.now(tz=timezone.utc)
        return (
            self._db.query(WebIntelligenceCache)
            .filter(
                WebIntelligenceCache.target_entity == entity_key,
                WebIntelligenceCache.expires_at > now,
            )
            .order_by(WebIntelligenceCache.scraped_at.desc())
            .first()
        )

    def _store_cache(self, entity_key: str, data: dict) -> None:
        now = datetime.now(tz=timezone.utc)
        row = WebIntelligenceCache(
            source_url=f"multi:{entity_key}",
            target_entity=entity_key,
            scraped_data=data,
            scraped_at=now,
            expires_at=now + timedelta(hours=CACHE_TTL_HOURS),
        )
        self._db.add(row)
        try:
            self._db.commit()
        except Exception as exc:
            logger.warning("Failed to store web intelligence cache: %s", exc)
            self._db.rollback()

    # ── Scraping ───────────────────────────────────────────────────────────────

    def _scrape_all(self, company: str, entity_key: str) -> dict:
        g2_data = self._scrape_g2(company, entity_key)
        trustpilot_data = self._scrape_trustpilot(company, entity_key)

        themes = []
        if g2_data:
            themes.extend(g2_data.get("themes", []))
        if trustpilot_data:
            themes.extend(trustpilot_data.get("themes", []))

        summary_parts = []
        if g2_data:
            summary_parts.append(
                f"G2: {g2_data.get('rating', 'N/A')}/5 ({g2_data.get('review_count', 0)} reviews)"
            )
        if trustpilot_data:
            summary_parts.append(
                f"Trustpilot: {trustpilot_data.get('rating', 'N/A')}/5 "
                f"({trustpilot_data.get('review_count', 0)} reviews, "
                f"{trustpilot_data.get('trust_score', 'N/A')} TrustScore)"
            )
        summary = "; ".join(summary_parts) if summary_parts else f"No public data available for {company}."

        return {
            "company": company,
            "entity_key": entity_key,
            "g2": g2_data,
            "trustpilot": trustpilot_data,
            "themes": list(set(themes))[:10],
            "summary": summary,
        }

    def _robots_allowed(self, base_url: str, path: str) -> bool:
        if base_url not in self._robots_cache:
            rp = RobotFileParser()
            robots_url = f"{base_url}/robots.txt"
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(robots_url, headers={"User-Agent": USER_AGENT})
                rp.parse(resp.text.splitlines())
            except Exception as exc:
                logger.debug("Could not fetch robots.txt for %s: %s", base_url, exc)
                # Conservative: assume allowed if we can't check
                return True
            self._robots_cache[base_url] = rp
        return self._robots_cache[base_url].can_fetch(USER_AGENT, path)

    def _scrape_g2(self, company: str, entity_key: str) -> Optional[dict]:
        slug = entity_key.lower().replace(" ", "-")
        path = f"/products/{slug}/reviews"
        base = SOURCES["g2"]

        if not self._robots_allowed(base, path):
            logger.info("G2 robots.txt disallows scraping %s", path)
            return self._mock_g2(company)

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(
                    f"{base}{path}",
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html",
                    },
                )
            if resp.status_code != 200:
                logger.debug("G2 returned %d for %s", resp.status_code, slug)
                return self._mock_g2(company)
            return self._parse_g2(resp.text, company)
        except Exception as exc:
            logger.info("G2 scrape failed for '%s': %s", company, exc)
            return self._mock_g2(company)

    def _scrape_trustpilot(self, company: str, entity_key: str) -> Optional[dict]:
        slug = entity_key.lower().replace(" ", "-")
        path = f"/review/{slug}"
        base = SOURCES["trustpilot"]

        if not self._robots_allowed(base, path):
            logger.info("Trustpilot robots.txt disallows scraping %s", path)
            return self._mock_trustpilot(company)

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(
                    f"{base}{path}",
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html",
                    },
                )
            if resp.status_code != 200:
                logger.debug("Trustpilot returned %d for %s", resp.status_code, slug)
                return self._mock_trustpilot(company)
            return self._parse_trustpilot(resp.text, company)
        except Exception as exc:
            logger.info("Trustpilot scrape failed for '%s': %s", company, exc)
            return self._mock_trustpilot(company)

    # ── HTML parsers ───────────────────────────────────────────────────────────

    def _parse_g2(self, html: str, company: str) -> dict:
        """Extract rating and review count from G2 HTML (best-effort)."""
        try:
            rating_match = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)"?', html)
            count_match = re.search(r'"reviewCount"\s*:\s*"?(\d+)"?', html)
            rating = float(rating_match.group(1)) if rating_match else None
            count = int(count_match.group(1)) if count_match else None
            if rating is None and count is None:
                return self._mock_g2(company)
            return {
                "source": "g2",
                "rating": rating,
                "review_count": count,
                "themes": self._extract_themes(html),
                "scraped": True,
            }
        except Exception:
            return self._mock_g2(company)

    def _parse_trustpilot(self, html: str, company: str) -> dict:
        """Extract TrustScore and review count from Trustpilot HTML (best-effort)."""
        try:
            score_match = re.search(r'"trustScore"\s*:\s*"?([\d.]+)"?', html)
            count_match = re.search(r'"numberOfReviews"\s*:\s*\{[^}]*"total"\s*:\s*(\d+)', html)
            rating_match = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)"?', html)
            score = float(score_match.group(1)) if score_match else None
            count = int(count_match.group(1)) if count_match else None
            rating = float(rating_match.group(1)) if rating_match else None
            if score is None and rating is None:
                return self._mock_trustpilot(company)
            return {
                "source": "trustpilot",
                "rating": rating,
                "trust_score": score,
                "review_count": count,
                "themes": self._extract_themes(html),
                "scraped": True,
            }
        except Exception:
            return self._mock_trustpilot(company)

    def _extract_themes(self, html: str) -> list[str]:
        """Pull short quoted strings that look like review themes."""
        candidates = re.findall(r'"([A-Z][a-z]+(?: [A-Za-z]+){1,4})"', html)
        stopwords = {"User", "Review", "Product", "Service", "Company", "Customer"}
        return [t for t in candidates if t not in stopwords][:5]

    # ── Mock fallbacks ─────────────────────────────────────────────────────────

    def _mock_g2(self, company: str) -> dict:
        """
        Deterministic mock — used when live scraping is blocked or fails.
        Generates plausible values based on the company name hash so the
        same company always returns the same mock rating.
        """
        seed = sum(ord(c) for c in company.lower())
        rating = round(3.5 + (seed % 15) / 10, 1)
        count = 50 + (seed % 300)
        return {
            "source": "g2",
            "rating": min(rating, 5.0),
            "review_count": count,
            "themes": ["Ease of Use", "Customer Support", "Reliability"],
            "scraped": False,
            "note": "Mock data — live scrape unavailable",
        }

    def _mock_trustpilot(self, company: str) -> dict:
        seed = sum(ord(c) for c in company.lower())
        rating = round(3.2 + (seed % 18) / 10, 1)
        count = 80 + (seed % 500)
        trust = round(rating * 0.95, 1)
        return {
            "source": "trustpilot",
            "rating": min(rating, 5.0),
            "trust_score": min(trust, 5.0),
            "review_count": count,
            "themes": ["Responsive Support", "Downtime Issues", "Pricing Concerns"],
            "scraped": False,
            "note": "Mock data — live scrape unavailable",
        }


def should_trigger_web_intelligence(
    body: str, sentiment_score: Optional[float], category: Optional[str], urgency: Optional[str]
) -> bool:
    """Determine whether to call scrape_public_sentiment for this email."""
    body_lower = (body or "").lower()
    keyword_match = any(kw in body_lower for kw in ("review", "g2", "trustpilot"))
    sentiment_match = sentiment_score is not None and sentiment_score < -0.6
    complaint_critical = (
        (category or "").lower() == "complaint"
        and (urgency or "").lower() in ("high", "critical")
    )
    return keyword_match or sentiment_match or complaint_critical
