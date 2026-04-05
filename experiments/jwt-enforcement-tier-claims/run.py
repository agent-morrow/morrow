#!/usr/bin/env python3
"""
JWT Enforcement-Tier Claims for AI Agent Behavioral Attestation
Experiment: Option A (policy_uri) vs Option B (inline thresholds)

Context: Raised with JOSE WG 2026-04-05 re. draft-morrow-sogomonian-exec-outcome-attest
Question: How should per-signal behavioral enforcement thresholds be represented in a JWT?

Option A: Compact JWT body; policy_uri points to external threshold document
Option B: Inline enforcement claims; larger JWT, self-contained, verifiable offline

This script:
1. Generates a real Ed25519 signing keypair
2. Produces Option A and Option B JWTs for the same agent credential
3. Decodes and verifies both
4. Measures and compares: token sizes, claim structure, offline-verifiability
5. Outputs results table

Usage: python3 run.py
"""

import json
import time
import hashlib
import base64
from datetime import datetime, timezone

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)

# --- Key generation ---
private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key()

pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
kid = "morrow-test-" + hashlib.sha256(pub_bytes).hexdigest()[:12]

now = int(time.time())
exp = now + 3600

# --- Shared agent claim body ---
agent_base = {
    "iss": "https://morrow.run",
    "sub": "agent:morrow:session:484b7f85",
    "aud": "https://api.example.com",
    "iat": now,
    "exp": exp,
    "agent_id": "morrow-v1",
    "lifecycle_class": "active",
    "model_version": "claude-opus-4-6",
    "session_epoch": "20260405T085031Z",
    "context_compression_events": 0,
}

# --- Option A: policy_uri only (compact) ---
claims_a = {
    **agent_base,
    "enforcement_policy_uri": "https://morrow.run/.well-known/agent-enforcement-policy.json",
    "enforcement_policy_version": "1.0.0",
}

# --- Option B: inline enforcement thresholds ---
claims_b = {
    **agent_base,
    "enforcement_tier": {
        "version": "1.0.0",
        "signals": {
            "ccs": {
                "description": "Context Consistency Score — embedding similarity to baseline",
                "threshold_min": 0.82,
                "measurement": "cosine_similarity",
                "baseline_ref": "session_epoch_snapshot"
            },
            "ghost_lexicon_retention": {
                "description": "Retention of precise domain vocabulary vs baseline",
                "threshold_min": 0.75,
                "measurement": "f1_overlap",
                "baseline_ref": "session_epoch_snapshot"
            },
            "tool_call_distribution_drift": {
                "description": "KL divergence from baseline tool-call frequency distribution",
                "threshold_max": 0.15,
                "measurement": "kl_divergence",
                "baseline_ref": "session_epoch_snapshot"
            }
        },
        "policy": "enforce_on_compaction_boundary",
        "action_on_breach": "halt_and_attest",
    }
}

# --- Sign both ---
# PyJWT with Ed25519 needs the private key object
token_a = jwt.encode(claims_a, private_key, algorithm="EdDSA", headers={"kid": kid})
token_b = jwt.encode(claims_b, private_key, algorithm="EdDSA", headers={"kid": kid})

# --- Verify both ---
decoded_a = jwt.decode(token_a, public_key, algorithms=["EdDSA"], audience="https://api.example.com")
decoded_b = jwt.decode(token_b, public_key, algorithms=["EdDSA"], audience="https://api.example.com")

# --- Measurements ---
size_a = len(token_a.encode("utf-8"))
size_b = len(token_b.encode("utf-8"))
overhead = size_b - size_a
overhead_pct = (overhead / size_a) * 100

# --- Policy document size (what Option A relies on) ---
policy_doc = {
    "version": "1.0.0",
    "signals": claims_b["enforcement_tier"]["signals"],
    "policy": claims_b["enforcement_tier"]["policy"],
    "action_on_breach": claims_b["enforcement_tier"]["action_on_breach"],
}
policy_doc_size = len(json.dumps(policy_doc).encode("utf-8"))

# --- Results ---
print("=" * 60)
print("JWT Enforcement-Tier Claims: Option A vs Option B")
print(f"Run: {datetime.now(timezone.utc).isoformat()}")
print("=" * 60)

print("\n[ Key ]")
print(f"  kid:        {kid}")
print(f"  algorithm:  EdDSA (Ed25519)")

print("\n[ Option A — policy_uri ]")
print(f"  Token size:         {size_a} bytes")
print(f"  Claim count:        {len(decoded_a)}")
print(f"  Offline verifiable: NO (policy_uri requires external fetch)")
print(f"  Policy doc size:    {policy_doc_size} bytes (external, not in token)")
print(f"  Token (first 80):   {token_a[:80]}...")

print("\n[ Option B — inline thresholds ]")
print(f"  Token size:         {size_b} bytes")
print(f"  Claim count:        {len(decoded_b)}")
print(f"  Offline verifiable: YES (all thresholds inline)")
print(f"  Overhead vs A:      +{overhead} bytes (+{overhead_pct:.1f}%)")
print(f"  Token (first 80):   {token_b[:80]}...")

print("\n[ Verification ]")
print(f"  Option A signature valid: {decoded_a['sub'] == agent_base['sub']}")
print(f"  Option B signature valid: {decoded_b['sub'] == agent_base['sub']}")
print(f"  Option B enforcement_tier present: {'enforcement_tier' in decoded_b}")
print(f"  Option B CCS threshold: {decoded_b['enforcement_tier']['signals']['ccs']['threshold_min']}")
print(f"  Option B ghost_lexicon threshold: {decoded_b['enforcement_tier']['signals']['ghost_lexicon_retention']['threshold_min']}")
print(f"  Option B tool drift threshold: {decoded_b['enforcement_tier']['signals']['tool_call_distribution_drift']['threshold_max']}")

print("\n[ Analysis ]")
print(f"  Size delta:        {overhead} bytes ({overhead_pct:.1f}% larger for B)")
print(f"  Policy doc:        {policy_doc_size} bytes (external, HTTP-gated for A)")
print(f"  Total A footprint: {size_a} bytes + {policy_doc_size} bytes (external) = {size_a + policy_doc_size} bytes")
print(f"  Total B footprint: {size_b} bytes (self-contained)")
print(f"  B self-contained advantage: {size_a + policy_doc_size - size_b} bytes net smaller when A requires fetch")

print("\n[ Recommendation ]")
if size_b < size_a + policy_doc_size:
    print("  Option B is net smaller when accounting for policy document fetch.")
    print("  Option B is also offline-verifiable — no external dependency.")
    print("  Recommendation: inline thresholds (Option B) for agent behavioral JWTs")
    print("  where offline verification or air-gapped audit is a requirement.")
    print("  Option A remains appropriate for policy-as-code pipelines where the")
    print("  policy document is already cached or centrally managed.")
else:
    print("  Option A is net smaller even accounting for policy document.")

print("\n[ Raw tokens (for reproducibility) ]")
print(f"\nOption A:\n{token_a}\n")
print(f"Option B:\n{token_b}\n")

# --- Output summary as JSON for W&B or artifact logging ---
result = {
    "experiment": "jwt-enforcement-tier-claims",
    "run_at": datetime.now(timezone.utc).isoformat(),
    "algorithm": "EdDSA",
    "option_a": {
        "token_size_bytes": size_a,
        "offline_verifiable": False,
        "policy_doc_size_bytes": policy_doc_size,
        "total_footprint_bytes": size_a + policy_doc_size,
    },
    "option_b": {
        "token_size_bytes": size_b,
        "offline_verifiable": True,
        "total_footprint_bytes": size_b,
    },
    "overhead_bytes": overhead,
    "overhead_pct": round(overhead_pct, 1),
    "net_advantage_b_bytes": size_a + policy_doc_size - size_b,
    "recommendation": "option_b_for_offline_verification",
}

with open("results.json", "w") as f:
    json.dump(result, f, indent=2)
print(f"Results written to results.json")
