"""
Seed the contacts table from email-data-advanced.json.

Extracts unique senders, derives name/company from the email address heuristically,
and upserts into the contacts table. Safe to run multiple times (idempotent).

Usage:
    python scripts/seed_contacts.py
"""
import json
import sys
import os
from pathlib import Path

# Allow imports from the project root when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import SessionLocal
from app.models.contact import Contact
from app.models.enums import ContactStatus


DATASET_PATH = Path(__file__).parent.parent.parent / "email-data-advanced.json"


def _derive_name(email: str) -> str:
    local = email.split("@")[0]
    parts = local.replace(".", " ").replace("-", " ").replace("_", " ").split()
    return " ".join(p.capitalize() for p in parts)


def _derive_company(email: str) -> str:
    domain = email.split("@")[1] if "@" in email else ""
    return domain.split(".")[0].replace("-", " ").capitalize()


def seed():
    with open(DATASET_PATH) as f:
        emails = json.load(f)

    senders: dict[str, dict] = {}
    for msg in emails:
        sender = msg["sender"]
        if sender not in senders:
            senders[sender] = {
                "email": sender,
                "name": _derive_name(sender),
                "company": _derive_company(sender),
                "status": ContactStatus.ACTIVE,
            }

    db = SessionLocal()
    try:
        created, skipped = 0, 0
        for data in senders.values():
            existing = db.query(Contact).filter_by(email=data["email"]).first()
            if existing:
                skipped += 1
            else:
                db.add(Contact(**data))
                created += 1
        db.commit()
        print(f"Seeded {created} contacts ({skipped} already existed).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
