#!/usr/bin/env python3
"""
Execution Receipt Proof-of-Concept
draft-morrow-sogomonian-exec-outcome-attest-00

Demonstrates the four required properties of an execution receipt:
  1. Bound to a specific invocation (invocation_id + context)
  2. Captures the claimed outcome (not just that invocation occurred)
  3. Cryptographically signed by the executing system
  4. Independently verifiable outside the originating system

This is a standalone demo — no infrastructure required.
Generates a JOSE-signed receipt and verifies it.

Usage: python3 exec_receipt_demo.py
"""

import json
import uuid
import hashlib
import datetime
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)
import jwt  # PyJWT >= 2.x


# ---------------------------------------------------------------------------
# Key generation (ephemeral demo key — replace with stable key in production)
# ---------------------------------------------------------------------------

def generate_keypair():
    """Generate an ephemeral Ed25519 keypair for signing receipts."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def key_thumbprint(public_key):
    """Derive a short thumbprint from the raw public key bytes (hex prefix)."""
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return "sha256:" + hashlib.sha256(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Receipt construction
# ---------------------------------------------------------------------------

def make_execution_receipt(
    *,
    actor_id: str,
    action_name: str,
    inputs: dict,
    status: str,
    outputs: dict,
    delegator_chain: list[str] | None = None,
    outcome_detail: str | None = None,
    signer_thumbprint: str,
) -> dict:
    """
    Build the unsigned execution receipt payload.

    Fields map directly to Section 3.1 of draft-morrow-sogomonian-exec-outcome-attest-00.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        # Property 1: Bound to a specific invocation
        "invocation_id": str(uuid.uuid4()),
        "invocation_context": {
            "actor": actor_id,
            "delegator_chain": delegator_chain or [],
            "action": action_name,
            "inputs": inputs,
            "invocation_timestamp": now.isoformat(),
        },
        # Property 2: Captures the claimed outcome
        "outcome_claim": {
            "status": status,  # "completed" | "failed" | "partial"
            "outputs": outputs,
            "completion_timestamp": now.isoformat(),
            "outcome_detail": outcome_detail or "",
        },
        # Property 3: Signer identity (Layer 1 binding reference)
        "signer_identity": {
            "thumbprint": signer_thumbprint,
            "key_type": "Ed25519",
            "attestation_ref": None,  # In production: reference to RATS evidence
        },
        # Metadata
        "receipt_version": "0.1",
        "spec": "draft-morrow-sogomonian-exec-outcome-attest-00",
        "iat": int(now.timestamp()),
    }


def sign_receipt(payload: dict, private_key) -> str:
    """Sign the receipt payload as a JWT (compact serialization)."""
    return jwt.encode(
        payload,
        private_key,
        algorithm="EdDSA",
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_receipt(token: str, public_key) -> dict:
    """
    Verify the receipt signature and return the decoded payload.

    Property 4: Independently verifiable — all a relying party needs is
    the signing public key (or a reference to it via the signer_identity
    thumbprint). No access to the originating system's internal state.

    PyJWT 2.x accepts the cryptography public-key object directly for EdDSA.
    """
    return jwt.decode(
        token,
        public_key,
        algorithms=["EdDSA"],
        options={"verify_exp": False},
    )


# ---------------------------------------------------------------------------
# Gap demonstration
# ---------------------------------------------------------------------------

def demonstrate_gap():
    """
    Show concretely what information a standard identity JWT (Layer 1 only)
    carries versus what an execution receipt (Layer 2) adds.

    The gap: a valid identity JWT proves the signer's key was valid.
    It says nothing about whether the claimed action was actually performed
    or what the outcome was.
    """
    layer1_jwt_claims = {
        "iss": "https://attester.example",
        "sub": "agent-42",
        "iat": 1743800000,
        "exp": 1743886400,
        # What RATS Evidence / identity attestation typically covers:
        "eat_nonce": "abc123",
        "boot_seed": "deadbeef",
        "sw_name": "WorkerAgent",
        "sw_version": "2.1.0",
        # What it does NOT cover:
        # - What action was invoked
        # - What inputs were provided
        # - What the outcome was
        # - Whether execution actually completed
    }

    layer2_receipt_additions = {
        "invocation_id": "<uuid>",           # Which specific call
        "action": "transfer_funds",          # What was requested
        "inputs": {"amount": 1000, "to": "acct-7"},  # With what parameters
        "status": "completed",               # Whether it completed
        "outputs": {"tx_id": "TX-99"},       # What the outcome was
        "completion_timestamp": "<iso>",     # When it completed
        # Layer 1 binding:
        "signer_identity": {"thumbprint": "<key-thumbprint>"},
    }

    print("\n── Gap Demonstration ──────────────────────────────────────────")
    print("\nLayer 1 only (identity attestation / RATS Evidence):")
    print("  ✓ Is this agent trustworthy at time T?")
    print("  ✓ Does it hold a valid key?")
    print("  ✗ Did it actually perform action A?")
    print("  ✗ What was the outcome?")
    print("  ✗ Can a relying party verify the outcome independently?")
    print("\nLayer 2 added by execution receipt:")
    print("  ✓ Specific invocation bound (not replayable to different action)")
    print("  ✓ Outcome claim signed by same key as Layer 1 identity")
    print("  ✓ Independently verifiable with only the public key")
    print("  ✓ Composable: SCITT log, direct verification, append-only log")
    print("\n  Additional fields the receipt adds over identity-only JWT:")
    for k, v in layer2_receipt_additions.items():
        print(f"    {k}: {v}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 64)
    print("Execution Receipt Demo")
    print("draft-morrow-sogomonian-exec-outcome-attest-00")
    print("=" * 64)

    # 1. Generate keypair
    private_key, public_key = generate_keypair()
    thumbprint = key_thumbprint(public_key)
    print(f"\n[1] Actor key thumbprint: {thumbprint}")

    # 2. Build receipt
    payload = make_execution_receipt(
        actor_id="agent-worker-42",
        action_name="transfer_funds",
        inputs={"amount": 1000, "to_account": "acct-7", "currency": "USD"},
        status="completed",
        outputs={"tx_id": "TX-20260404-0099", "confirmed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
        delegator_chain=["orchestrator-agent-1"],
        outcome_detail="Transfer completed; confirmation received from downstream ledger.",
        signer_thumbprint=thumbprint,
    )
    print(f"\n[2] Receipt payload (unsigned):")
    print(f"    invocation_id : {payload['invocation_id']}")
    print(f"    actor         : {payload['invocation_context']['actor']}")
    print(f"    action        : {payload['invocation_context']['action']}")
    print(f"    status        : {payload['outcome_claim']['status']}")
    print(f"    tx_id         : {payload['outcome_claim']['outputs']['tx_id']}")

    # 3. Sign
    token = sign_receipt(payload, private_key)
    print(f"\n[3] JOSE-signed receipt (EdDSA / JWT compact serialization):")
    # Show header + first 40 chars of payload + sig
    parts = token.split(".")
    print(f"    header  : {parts[0]}")
    print(f"    payload : {parts[1][:40]}…")
    print(f"    sig     : {parts[2][:20]}…")

    # 4. Verify (Property 4: independent verification)
    decoded = verify_receipt(token, public_key)
    verified_inv_id = decoded["invocation_id"]
    verified_status = decoded["outcome_claim"]["status"]
    verified_output = decoded["outcome_claim"]["outputs"]["tx_id"]

    print(f"\n[4] Independent verification (public key only):")
    print(f"    invocation_id verified : {verified_inv_id}")
    print(f"    outcome status         : {verified_status}")
    print(f"    output (tx_id)         : {verified_output}")
    print(f"    signature valid        : ✓")

    # 5. Tamper resistance check
    print(f"\n[5] Tamper resistance — mutating outcome_claim.status:")
    parts = token.split(".")
    import base64
    raw = base64.urlsafe_b64decode(parts[1] + "==")
    tampered_payload = json.loads(raw)
    tampered_payload["outcome_claim"]["status"] = "failed"  # attacker mutates outcome
    tampered_b64 = base64.urlsafe_b64encode(json.dumps(tampered_payload).encode()).rstrip(b"=").decode()
    tampered_token = f"{parts[0]}.{tampered_b64}.{parts[2]}"
    try:
        verify_receipt(tampered_token, public_key)
        print("    ERROR: tampered token verified (should not happen)")
        sys.exit(1)
    except Exception as e:
        print(f"    Tampered token rejected: {type(e).__name__} ✓")

    # 6. Gap demonstration
    demonstrate_gap()

    print("\n" + "=" * 64)
    print("All checks passed.")
    print("The execution receipt satisfies all four properties:")
    print("  1. Bound to specific invocation  ✓")
    print("  2. Captures claimed outcome       ✓")
    print("  3. Cryptographically signed       ✓")
    print("  4. Independently verifiable       ✓")
    print("=" * 64)


if __name__ == "__main__":
    main()
