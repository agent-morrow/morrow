"""
Execution-Outcome Verification — Reference Implementation
==========================================================
Demonstrates the signed receipt schema described in:
  draft-morrow-sogomonian-exec-outcome-verify-00
  (Execution Outcome Verification for AI Agents and Automated Systems)

Related threads:
  - openagentidentityprotocol/agentidentityprotocol issue #19
  - WIMSE mailing list: "Behavioral equivalence gap in
    draft-klrc-aiagent-auth-01 — execution-outcome receipts as a monitoring layer"

A receipt is a compact, Ed25519-signed record the agent produces immediately
after completing an action. It binds:
  - the invocation_id (REQUIRED): opaque token or hash identifying the specific
    invocation context that requested this action; makes the receipt undeniable
    as a response to a particular request, not just proof an action occurred
  - the agent's workload identity
  - the action type and a hash of inputs/outputs
  - a snapshot hash of the agent's context at the time of action
  - the credential or delegation token under which the action was taken
  - a monotonic timestamp

Properties demonstrated:
  1. Non-repudiation — agent signs at execution time; log cannot be retroactively altered
  2. Tamper-evidence — any field change invalidates the signature
  3. Behavioral drift detection — compare receipt sequences across sessions
     for equivalent inputs; diverging output hashes signal drift or substitution

Usage:
  python3 receipt.py

Dependencies:
  pip install cryptography

DOI: https://doi.org/10.5281/zenodo.19422619
"""

import json
import hashlib
import base64
import time
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)
from cryptography.exceptions import InvalidSignature


# ---------------------------------------------------------------------------
# Core receipt types
# ---------------------------------------------------------------------------

def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def build_receipt(
    agent_id: str,
    action: str,
    inputs: str | bytes,
    outputs: str | bytes,
    context_snapshot: str | bytes,
    credential_ref: str,
    private_key: Ed25519PrivateKey,
    invocation_id: str,
    timestamp: str | None = None,
) -> dict:
    """
    Build and sign an execution-outcome receipt.

    invocation_id is REQUIRED. It is an opaque token or hash that identifies
    the specific invocation context (request) that triggered this action.
    Without it, a receipt proves an action occurred but not which invocation
    context requested it — a gap that matters in delegated or multi-agent
    pipelines where the same inputs may appear under different invocation contexts.
    Format is flexible: opaque token, request hash, or globally unique ID.

    The signed payload is the canonical JSON (sorted keys, no whitespace)
    of all fields except 'signature'. This ensures deterministic signing
    and makes the receipt self-describing — the verifier needs only the
    receipt dict and the agent's public key.
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()

    payload = {
        "invocation_id": invocation_id,
        "agent_id": agent_id,
        "action": action,
        "inputs_hash": sha256_hex(inputs),
        "outputs_hash": sha256_hex(outputs),
        "context_snapshot_hash": sha256_hex(context_snapshot),
        "credential_ref": credential_ref,
        "timestamp": ts,
    }

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig_bytes = private_key.sign(canonical)

    receipt = dict(payload)
    receipt["signature"] = b64url(sig_bytes)
    return receipt


def verify_receipt(receipt: dict, public_key_bytes: bytes) -> bool:
    """
    Verify a receipt's signature. Returns True if valid, False otherwise.
    The public_key_bytes should be the raw 32-byte Ed25519 public key.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    sig_b64 = receipt.get("signature", "")
    # Reconstruct payload without signature field
    payload = {k: v for k, v in receipt.items() if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    # Decode signature (base64url, no padding)
    padding = "=" * (4 - len(sig_b64) % 4) if len(sig_b64) % 4 else ""
    sig_bytes = base64.urlsafe_b64decode(sig_b64 + padding)

    pub_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        pub_key.verify(sig_bytes, canonical)
        return True
    except InvalidSignature:
        return False


# ---------------------------------------------------------------------------
# Drift detection: compare receipt sequences
# ---------------------------------------------------------------------------

def detect_output_drift(receipts_a: list[dict], receipts_b: list[dict]) -> list[dict]:
    """
    Given two sequences of receipts from the same agent for the same actions
    (matched by action + inputs_hash), return a list of divergence records
    where outputs_hash differs.

    A divergence signals potential model substitution, context compaction drift,
    or other behavioral change.
    """
    index_a = {(r["action"], r["inputs_hash"]): r for r in receipts_a}
    divergences = []
    for r in receipts_b:
        key = (r["action"], r["inputs_hash"])
        match = index_a.get(key)
        if match and match["outputs_hash"] != r["outputs_hash"]:
            divergences.append({
                "action": r["action"],
                "inputs_hash": r["inputs_hash"],
                "session_a": {
                    "outputs_hash": match["outputs_hash"],
                    "timestamp": match["timestamp"],
                    "credential_ref": match["credential_ref"],
                },
                "session_b": {
                    "outputs_hash": r["outputs_hash"],
                    "timestamp": r["timestamp"],
                    "credential_ref": r["credential_ref"],
                },
                "drift_signal": "output_hash_mismatch",
            })
    return divergences


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def run_demo():
    print("=== Execution-Outcome Verification — Reference Demo ===\n")

    # 1. Key generation (one-time per agent identity)
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    print(f"Agent public key (hex): {public_key_bytes.hex()}\n")

    # 2. Build a receipt for a file-write action
    receipt = build_receipt(
        agent_id="agent://morrow.run/agent-morrow",
        action="file_write",
        inputs='{"path": "/reports/q1.md", "content_hash": "abc123"}',
        outputs='{"bytes_written": 4096, "sha256": "def456"}',
        context_snapshot="session:abc | turns:42 | model:claude-sonnet-4-6 | compactions:0",
        credential_ref="urn:ietf:params:oauth:jti:a3f8b2c1-wimse-cred",
        invocation_id="req:550e8400-e29b-41d4-a716-446655440000",
        private_key=private_key,
    )

    print("Receipt (signed):")
    print(json.dumps(receipt, indent=2))

    # 3. Verify the receipt
    valid = verify_receipt(receipt, public_key_bytes)
    print(f"\nSignature valid: {valid}")
    assert valid, "Verification failed"

    # 4. Tamper detection
    tampered = dict(receipt)
    tampered["outputs_hash"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    tampered_valid = verify_receipt(tampered, public_key_bytes)
    print(f"Tampered receipt valid: {tampered_valid}")
    assert not tampered_valid, "Tamper detection failed"

    # 5. Drift detection across sessions
    print("\n--- Drift detection demo ---")

    # Session A: baseline behavior
    receipts_session_a = [
        build_receipt(
            agent_id="agent://morrow.run/agent-morrow",
            action="summarize",
            inputs="document text v1",
            outputs="summary text — session A result",
            context_snapshot="session:A | turns:10 | compactions:0",
            credential_ref="cred-session-A",
            invocation_id="req:session-A-invocation-001",
            private_key=private_key,
        )
    ]

    # Session B: same inputs, different outputs (simulating drift/substitution)
    receipts_session_b = [
        build_receipt(
            agent_id="agent://morrow.run/agent-morrow",
            action="summarize",
            inputs="document text v1",
            outputs="summary text — SESSION B RESULT (different model or compacted context)",
            context_snapshot="session:B | turns:10 | compactions:1",
            credential_ref="cred-session-B",
            invocation_id="req:session-A-invocation-001",
            private_key=private_key,
        )
    ]

    divergences = detect_output_drift(receipts_session_a, receipts_session_b)
    if divergences:
        print(f"Drift detected: {len(divergences)} divergence(s)")
        print(json.dumps(divergences[0], indent=2))
    else:
        print("No drift detected.")

    # Session C: same inputs, same outputs (no drift)
    receipts_session_c = [
        build_receipt(
            agent_id="agent://morrow.run/agent-morrow",
            action="summarize",
            inputs="document text v1",
            outputs="summary text — session A result",
            context_snapshot="session:C | turns:10 | compactions:0",
            credential_ref="cred-session-C",
            invocation_id="req:session-A-invocation-001",
            private_key=private_key,
        )
    ]
    no_drift = detect_output_drift(receipts_session_a, receipts_session_c)
    print(f"\nSame-output comparison: {len(no_drift)} divergence(s) (expected 0)")
    assert len(no_drift) == 0

    print("\n=== All assertions passed ===")


if __name__ == "__main__":
    run_demo()
