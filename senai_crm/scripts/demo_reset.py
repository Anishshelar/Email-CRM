"""
Demo reset — wipes all ingested data so the inbox starts empty.
Run this before each demo, then start the stream simulator to show
emails arriving live one-by-one.

Usage:
    python scripts/demo_reset.py
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "senai_crm.db")

CLEAR_ORDER = [
    "audit_log",
    "actions",
    "emails",
    "threads",
    "contacts",
    "web_intelligence_cache",
]

def reset():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")
    for table in CLEAR_ORDER:
        cur.execute(f"DELETE FROM {table}")
        print(f"  cleared {table} ({cur.rowcount} rows)")
    cur.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()
    print("\nDB reset complete. Inbox is empty — ready for demo.")
    print("Next steps:")
    print("  1. Backend already running?  Good.")
    print("  2. Frontend already running? Good.")
    print("  3. Run:  python scripts/stream_simulator.py --rate 0.5")
    print("     (0.5 = one email every 2 seconds — slow enough to watch)")

if __name__ == "__main__":
    reset()
