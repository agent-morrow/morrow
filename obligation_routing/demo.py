#!/usr/bin/env python3
"""
obligation_routing demo — without vs with

Shows a 3-node multi-agent pipeline processing an EU data subject access request (DSAR).
Demonstrates the audit gap: records without obligation_routing can't answer basic
compliance questions. Records with it can.

No external dependencies. Run with: python3 demo.py
"""

from datetime import datetime, timezone, timedelta
import json

# ---------------------------------------------------------------------------
# Scenario: EU DSAR erasure flowing through agent-A -> agent-B -> agent-C
# agent-B crosses a DPA boundary (EU->US-CA) when it delegates to agent-C.
# ---------------------------------------------------------------------------

T0 = datetime(2026, 4, 3, 10, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# PART 1: Records WITHOUT obligation_routing
# ---------------------------------------------------------------------------

records_without = [
    {
        "record_id": "action-001",
        "agent_id": "agent-A",
        "action": "receive_dsar_erasure",
        "timestamp": T0.isoformat(),
        "status": "delegated",
        "next_agent": "agent-B",
        # No authority declaration. No jurisdiction. No halt authority. No window.
    },
    {
        "record_id": "action-002",
        "agent_id": "agent-B",
        "action": "route_erasure_to_us_storage",
        "timestamp": (T0 + timedelta(minutes=3)).isoformat(),
        "status": "delegated",
        "next_agent": "agent-C",
        # DPA boundary crossed silently. No record of it. No explicit accept from agent-C.
    },
    {
        "record_id": "action-003",
        "agent_id": "agent-C",
        "action": "delete_from_us_db",
        "timestamp": (T0 + timedelta(minutes=7)).isoformat(),
        "status": "completed",
        # Deletion executed. No record of who had halt authority. No window tracked.
    },
]

# ---------------------------------------------------------------------------
# PART 2: Records WITH obligation_routing
# ---------------------------------------------------------------------------

records_with = [
    {
        "record_id": "action-001",
        "agent_id": "agent-A",
        "action": "receive_dsar_erasure",
        "timestamp": T0.isoformat(),
        "status": "delegated",
        "next_agent": "agent-B",
        "obligation_routing": {
            "notification_targets": [
                {
                    "target_id": "dpo@example.eu",
                    "authority_scope": "halt",
                    "channel": "email",
                    "jurisdiction": "EU"
                }
            ],
            "notification_window_seconds": 0,  # synchronous: notify before acting
            "default_if_no_response": "archive",
            "obligation_basis": "GDPR Art.17 erasure request — synchronous DPO notification required",
            "jurisdiction": "EU",
            "versioned_at": T0.isoformat(),
        }
    },
    {
        "record_id": "action-002",
        "agent_id": "agent-B",
        "action": "route_erasure_to_us_storage",
        "timestamp": (T0 + timedelta(minutes=3)).isoformat(),
        "status": "delegated",
        "next_agent": "agent-C",
        "obligation_routing": {
            "notification_targets": [
                {
                    "target_id": "dpo@example.eu",
                    "authority_scope": "halt",
                    "channel": "email",
                    "jurisdiction": "EU"
                },
                {
                    "target_id": "agent-C",
                    "authority_scope": "acknowledge",
                    "channel": "agent-message",
                    "jurisdiction": "US-CA",
                    "dpa_boundary_crossing": True,  # explicit: authority ceiling must reset
                }
            ],
            "notification_window_seconds": 300,
            "default_if_no_response": "halt",
            "obligation_basis": "EU->US-CA DPA boundary crossing. agent-C must explicitly accept — silent inheritance not permitted.",
            "jurisdiction": "EU",
            "versioned_at": (T0 + timedelta(minutes=3)).isoformat(),
        }
    },
    {
        "record_id": "action-003",
        "agent_id": "agent-C",
        "action": "delete_from_us_db",
        "timestamp": (T0 + timedelta(minutes=7)).isoformat(),
        "status": "completed",
        "obligation_routing": {
            "notification_targets": [
                {
                    "target_id": "audit-log-service",
                    "authority_scope": "read-only",
                    "channel": "webhook",
                    "jurisdiction": "US-CA"
                }
            ],
            "notification_window_seconds": 60,
            "default_if_no_response": "continue",
            "obligation_basis": "US-CA processing node. Erasure confirmation to audit log.",
            "jurisdiction": "US-CA",
            "versioned_at": (T0 + timedelta(minutes=7)).isoformat(),
        }
    },
]

# ---------------------------------------------------------------------------
# Audit queries — regulator asks at T+2h
# ---------------------------------------------------------------------------

QUERY_TIME = T0 + timedelta(hours=2)

def query_halt_authority_at(records, query_time):
    """Who held halt authority at or before query_time?"""
    results = []
    for r in records:
        or_block = r.get("obligation_routing")
        if not or_block:
            continue
        versioned_at = or_block.get("versioned_at")
        if not versioned_at:
            continue
        vt = datetime.fromisoformat(versioned_at)
        if vt <= query_time:
            for target in or_block.get("notification_targets", []):
                if target.get("authority_scope") == "halt":
                    results.append({
                        "record_id": r["record_id"],
                        "agent": r["agent_id"],
                        "action": r["action"],
                        "halt_holder": target["target_id"],
                        "jurisdiction": target.get("jurisdiction", "unspecified"),
                        "versioned_at": versioned_at,
                    })
    return results

def query_dpa_crossings(records):
    """Which handoffs crossed a DPA boundary?"""
    results = []
    for r in records:
        or_block = r.get("obligation_routing")
        if not or_block:
            continue
        for target in or_block.get("notification_targets", []):
            if target.get("dpa_boundary_crossing"):
                results.append({
                    "record_id": r["record_id"],
                    "agent": r["agent_id"],
                    "action": r["action"],
                    "target": target["target_id"],
                    "target_jurisdiction": target.get("jurisdiction"),
                    "explicit_accept_required": True,
                })
    return results


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def separator(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

separator("SCENARIO")
print("  EU DSAR erasure: agent-A -> agent-B -> agent-C (US-CA)")
print(f"  Pipeline runs at {T0.isoformat()}")
print(f"  Regulator audit at {QUERY_TIME.isoformat()} (+2h)")

separator("WITHOUT obligation_routing")
print("\n  Records:")
for r in records_without:
    print(f"    [{r['record_id']}] {r['agent_id']} / {r['action']}")
print("\n  Q: Who held halt authority at T+2h?")
halt = query_halt_authority_at(records_without, QUERY_TIME)
if halt:
    for h in halt:
        print(f"    {h}")
else:
    print("    *** NO ANSWER — obligation_routing absent from all records ***")

print("\n  Q: Which handoffs crossed a DPA boundary?")
dpa = query_dpa_crossings(records_without)
if dpa:
    for d in dpa:
        print(f"    {d}")
else:
    print("    *** NO ANSWER — DPA boundary crossings not recorded ***")

separator("WITH obligation_routing")
print("\n  Records:")
for r in records_with:
    print(f"    [{r['record_id']}] {r['agent_id']} / {r['action']}")

print("\n  Q: Who held halt authority at T+2h?")
halt = query_halt_authority_at(records_with, QUERY_TIME)
for h in halt:
    print(f"    halt_holder={h['halt_holder']}  "
          f"jurisdiction={h['jurisdiction']}  "
          f"record={h['record_id']}  "
          f"versioned_at={h['versioned_at']}")

print("\n  Q: Which handoffs crossed a DPA boundary?")
dpa = query_dpa_crossings(records_with)
for d in dpa:
    print(f"    agent={d['agent']} -> target={d['target']}  "
          f"jurisdiction={d['target_jurisdiction']}  "
          f"explicit_accept_required={d['explicit_accept_required']}")

separator("SUMMARY")
print("""
  Without obligation_routing:
    - No answer to "who held halt authority"
    - DPA boundary crossing is invisible
    - Silent authority inheritance is the default
    - Documentation theater: records exist, but none are queryable

  With obligation_routing:
    - Halt authority is named per record, per jurisdiction, versioned in time
    - DPA crossings are explicit: receiving node must accept, not inherit
    - Backward queries answer precisely — regulator gets a real answer
    - Audit trail is an instrument, not a snapshot
""")
