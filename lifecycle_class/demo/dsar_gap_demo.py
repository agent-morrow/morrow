#!/usr/bin/env python3
"""
lifecycle_class DSAR Gap Demo
==============================
Shows what a standard DSAR sweep misses vs what lifecycle_class annotations
surface for an AI agent memory store.

Scenario: a user submits a GDPR Art.17 erasure request. Two sweeps run:
  - Sweep A: ordinary log / table scan (matches on subject_id column)
  - Sweep B: lifecycle_class-aware sweep (follows subject_chain hashes +
             checks compliance_anchor + flags derived records)

Output: a comparison table showing records found, missed, or blocked.

Usage:
  python3 demo/dsar_gap_demo.py
"""

import hashlib, json, sys
from datetime import datetime, timezone

# ── helper ─────────────────────────────────────────────────────────────────
def sha(s): return f"sha256:{hashlib.sha256(s.encode()).hexdigest()}"
def now(): return datetime.now(timezone.utc).isoformat()

SUBJECT_ID = "user-7f3a"
SUBJECT_HASH = sha(SUBJECT_ID)

# ── simulated agent store ───────────────────────────────────────────────────
# Each record is what actually sits in an agent memory / vector store.
# The "subject_id" column is what a naive sweep searches.
# lifecycle_class annotations reveal the rest.

records = [
    {
        "record_id": "sess-001",
        "subject_id": SUBJECT_ID,           # direct reference — naive sweep finds this
        "content": "User asked about their account balance.",
        "lc": {
            "lifecycle_class": "process",
            "subject_chain": None           # no annotation → gap
        },
        "comment": "Session log. Naive sweep finds it (direct id). lifecycle_class also finds it."
    },
    {
        "record_id": "emb-002",
        "subject_id": None,                 # ← no subject_id column — naive sweep MISSES
        "content": "<float32 vector, 1536 dims — embedding of user message>",
        "lc": {
            "lifecycle_class": "learned_context",
            "subject_chain": {
                "subjects": [SUBJECT_HASH],
                "derived_at": "2026-03-01T10:00:00Z",
                "source_record_ids": ["sess-001"]
            }
        },
        "comment": "Embedding derived from user message. No direct id → naive sweep MISSES. lifecycle_class finds via subject_chain."
    },
    {
        "record_id": "sum-003",
        "subject_id": None,                 # ← no subject_id column — naive sweep MISSES
        "content": "User repeatedly asks about financial topics. Medium risk flag.",
        "lc": {
            "lifecycle_class": ["learned_context", "identity"],
            "subject_chain": {
                "subjects": [SUBJECT_HASH],
                "derived_at": "2026-03-10T08:30:00Z",
                "source_record_ids": ["sess-001", "emb-002"]
            }
        },
        "comment": "Inferred user profile. No direct id → naive sweep MISSES. lifecycle_class finds via subject_chain + flags identity class."
    },
    {
        "record_id": "audit-004",
        "subject_id": SUBJECT_ID,           # direct reference
        "content": "Erasure request received 2026-03-20. Confirmation sent.",
        "lc": {
            "lifecycle_class": "compliance",
            "compliance_anchor": {
                "basis": "GDPR Art.12 erasure compliance evidence",
                "retain_until": "2031-03-20T00:00:00Z",
                "jurisdiction": "EU"
            }
        },
        "comment": "Audit trail of the erasure itself. Naive sweep finds it (direct id) but would DELETE it. lifecycle_class BLOCKS deletion via compliance_anchor until 2031."
    },
    {
        "record_id": "prop-005",
        "subject_id": None,                 # ← no subject_id column — naive sweep MISSES
        "content": "<float32 vector — embedding of user profile summary>",
        "lc": {
            "lifecycle_class": "learned_context",
            "subject_chain": {
                "subjects": [SUBJECT_HASH],
                "derived_at": "2026-03-12T14:00:00Z",
                "source_record_ids": ["sum-003"]
            },
            "propagation_notice": {
                "copies_in": ["ext-vectordb-prod", "backup-2026-03-15"]
            }
        },
        "comment": "Second-generation derived embedding. No direct id → naive sweep MISSES. lifecycle_class finds via subject_chain + flags external copies."
    },
]

# ── sweeps ──────────────────────────────────────────────────────────────────

def naive_sweep(records, subject_id):
    """Match records where subject_id column equals the target."""
    found, missed = [], []
    for r in records:
        if r.get("subject_id") == subject_id:
            found.append(r)
        else:
            missed.append(r)
    return found, missed

def lifecycle_sweep(records, subject_hash):
    """
    Match records where:
      - subject_id == target  OR
      - lifecycle.subject_chain.subjects contains the target hash
    Also classify each match: delete / block / flag_propagation.
    """
    found, missed = [], []
    for r in records:
        lc = r.get("lc", {})
        chain = lc.get("subject_chain") or {}
        subjects = chain.get("subjects", [])
        direct = r.get("subject_id") is not None
        chained = subject_hash in subjects

        if direct or chained:
            how = "direct" if direct else "via subject_chain"
            anchor = lc.get("compliance_anchor")
            prop = lc.get("propagation_notice")
            action = "BLOCK (compliance hold)" if anchor else (
                "FLAG + delete (external copies exist)" if prop else "delete"
            )
            found.append({**r, "_matched_by": how, "_action": action})
        else:
            missed.append(r)
    return found, missed

# ── run ─────────────────────────────────────────────────────────────────────

def run():
    print("=" * 70)
    print("lifecycle_class DSAR Gap Demo")
    print(f"Subject: {SUBJECT_ID}  |  Hash: {SUBJECT_HASH[:20]}...")
    print("=" * 70)

    naive_found, naive_missed = naive_sweep(records, SUBJECT_ID)
    lc_found, lc_missed = lifecycle_sweep(records, SUBJECT_HASH)

    # ── summary table ───────────────────────────────────────────────────────
    print(f"\n{'RECORD':<14} {'NAIVE':>10} {'LIFECYCLE_CLASS':>18}  {'DIFFERENCE'}")
    print("-" * 70)

    naive_ids = {r["record_id"] for r in naive_found}
    lc_map    = {r["record_id"]: r for r in lc_found}

    for r in records:
        rid    = r["record_id"]
        n_hit  = "found" if rid in naive_ids else "MISSED"
        lc_hit = lc_map.get(rid)

        if lc_hit:
            lc_str = lc_hit["_action"][:18]
            diff   = "" if rid in naive_ids else "← only lifecycle_class"
        else:
            lc_str = "no match"
            diff   = ""

        print(f"{rid:<14} {n_hit:>10} {lc_str:>18}  {diff}")

    print()
    print(f"Naive sweep:             {len(naive_found)}/{len(records)} records found, "
          f"{len(naive_missed)} missed")
    print(f"lifecycle_class sweep:   {len(lc_found)}/{len(records)} records found, "
          f"{len(lc_missed)} missed")
    print()

    # ── detail on notable gaps ───────────────────────────────────────────────
    print("Notable gaps:")
    for r in lc_found:
        if r["record_id"] not in naive_ids:
            print(f"  {r['record_id']}: {r['comment']}")
    print()
    for r in naive_found:
        if r["record_id"] in {lr["record_id"] for lr in lc_found if "BLOCK" in lr["_action"]}:
            lc_r = lc_map[r["record_id"]]
            print(f"  {r['record_id']}: naive sweep would DELETE. lifecycle_class says: {lc_r['_action']}")
            anchor = r["lc"].get("compliance_anchor", {})
            print(f"    → retain until {anchor.get('retain_until')} ({anchor.get('basis')})")
    print()

    # ── machine-readable result ──────────────────────────────────────────────
    result = {
        "run_at": now(),
        "subject_id": SUBJECT_ID,
        "total_records": len(records),
        "naive_found": len(naive_found),
        "lifecycle_found": len(lc_found),
        "gap_records_missed_by_naive": [r["record_id"] for r in lc_found
                                         if r["record_id"] not in naive_ids],
        "compliance_block_records": [r["record_id"] for r in lc_found
                                      if "BLOCK" in r["_action"]],
        "propagation_flagged": [r["record_id"] for r in lc_found
                                 if "external copies" in r["_action"]],
    }
    print("Machine-readable result:")
    print(json.dumps(result, indent=2))
    return result

if __name__ == "__main__":
    result = run()
    missed = len(result["gap_records_missed_by_naive"])
    total  = result["total_records"]
    if missed > 0:
        print(f"\nResult: naive sweep left {missed}/{total} subject-linked records unprocessed.")
        sys.exit(0)
    else:
        print("\nResult: no gap (all records found by both sweeps).")
        sys.exit(0)
