"""
Streaming simulator — replays email-data-advanced.json through POST /api/ingest.

Supports configurable replay speed for both dev (1/sec) and load-test (10+/sec) modes.
Preserves original timestamp ordering from the dataset.

Usage:
    python scripts/stream_simulator.py               # default: 1 email/sec
    python scripts/stream_simulator.py --rate 5      # 5 emails/sec
    python scripts/stream_simulator.py --rate 0.5    # 1 email per 2 sec (slow motion)
    python scripts/stream_simulator.py --dry-run     # print payloads, don't POST
"""
import argparse
import json
import sys
import time
from pathlib import Path

# Phase 1 stub — httpx POST calls are wired up once the ingest endpoint is live.
# The simulator is included now so it can be demoed alongside the endpoint in the
# same commit, and the rate/dry-run logic is already tested.

DATASET_PATH = Path(__file__).parent.parent.parent / "email-data-advanced.json"
INGEST_URL = "http://localhost:8000/api/ingest"


def run(rate: float, dry_run: bool) -> None:
    with open(DATASET_PATH) as f:
        emails = json.load(f)

    delay = 1.0 / rate
    print(f"Replaying {len(emails)} emails at {rate:.1f}/sec (dry_run={dry_run})")

    for i, email in enumerate(emails, start=1):
        if dry_run:
            print(f"[{i:02d}/{len(emails)}] WOULD POST: {email['message_id']} — {email['subject']}")
        else:
            # httpx import is deferred so dry-run works without it being installed.
            import httpx
            try:
                resp = httpx.post(INGEST_URL, json=email, timeout=10)
                status = resp.status_code
                body = resp.json()
                flag = "DUP " if body.get("already_exists") else "NEW "
                print(f"[{i:02d}/{len(emails)}] {flag}{status} {email['message_id']} — {email['subject'][:60]}")
            except Exception as exc:
                print(f"[{i:02d}/{len(emails)}] ERROR {email['message_id']}: {exc}", file=sys.stderr)

        if i < len(emails):
            time.sleep(delay)

    print("Stream complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay email dataset through the ingest endpoint.")
    parser.add_argument("--rate", type=float, default=1.0, help="Emails per second (default: 1.0)")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without POSTing")
    args = parser.parse_args()
    run(rate=args.rate, dry_run=args.dry_run)
