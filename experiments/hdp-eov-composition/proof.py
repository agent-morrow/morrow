"""
HDP + EOV Composition Proof
============================
Demonstrates that an HDP delegation token can be cryptographically bound
to an Execution Outcome Voucher (EOV) receipt.

The binding:
  1. Issue an HDP root token (Ed25519 / RFC 8785, via hdp-crewai)
  2. Compute SHA-256 of the canonical JSON form of that token
  3. Embed that hash as `delegation_token` in an EOV receipt
  4. Sign the EOV with a separate agent keypair
  5. Verify both signatures offline

Run:
  python3 proof.py

Expected output:
  ✓ HDP token issued and verified
  ✓ EOV receipt created with HDP delegation_token binding
  ✓ EOV signature verified
  ✓ delegation_token in EOV matches SHA-256(HDP canonical JSON)

Author: Morrow (morrow@morrow.run)
Date: 2026-04-05
Ref: https://morrow.run/posts/execution-outcome-attestation.html
"""

import hashlib
import json
import time
import uuid
import base64

import jcs
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hdp_crewai._crypto import sign_root, verify_root
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


# ── 1. Generate keys ──────────────────────────────────────────────────────────

# Human principal's signing key (issues the HDP root token)
human_private = Ed25519PrivateKey.generate()
human_private_bytes = human_private.private_bytes_raw()
human_public = human_private.public_key()

# Agent's signing key (signs the EOV receipt)
agent_private = Ed25519PrivateKey.generate()
agent_private_bytes = agent_private.private_bytes_raw()
agent_public = agent_private.public_key()

print("Keys generated.")


# ── 2. Issue HDP root token ───────────────────────────────────────────────────

now_ms = int(time.time() * 1000)
session_id = f"sess-proof-{uuid.uuid4().hex[:8]}"

unsigned_hdp = {
    "hdp": "0.1",
    "header": {
        "token_id": str(uuid.uuid4()),
        "issued_at": now_ms,
        "expires_at": now_ms + 3600_000,  # 1 hour
        "session_id": session_id,
        "version": "0.1",
    },
    "principal": {
        "id": "usr_alice_opaque",
        "id_type": "opaque",
        "display_name": "Alice Chen",
    },
    "scope": {
        "intent": "Analyze Q1 sales data and generate a summary report.",
        "data_classification": "confidential",
        "network_egress": False,
        "persistence": True,
        "authorized_tools": ["database_read", "file_write"],
        "authorized_resources": ["db://sales/q1-2026"],
        "max_hops": 3,
    },
    "chain": [],
}

kid = "alice-signing-key-v1"
signature = sign_root(unsigned_hdp, human_private_bytes, kid)
hdp_token = {**unsigned_hdp, "signature": signature}

# Verify the HDP token
ok = verify_root(hdp_token, human_public)
assert ok, "HDP root signature verification failed"
print("✓ HDP token issued and verified")


# ── 3. Compute HDP canonical hash ─────────────────────────────────────────────

hdp_canonical = jcs.canonicalize(hdp_token)
hdp_hash = hashlib.sha256(hdp_canonical).hexdigest()
print(f"  HDP SHA-256: {hdp_hash}")


# ── 4. Issue EOV receipt ──────────────────────────────────────────────────────

agent_pub_bytes = agent_public.public_bytes(Encoding.Raw, PublicFormat.Raw)
agent_pub_b64 = base64.urlsafe_b64encode(agent_pub_bytes).rstrip(b"=").decode()

eov_body = {
    "spec": "eov-00",
    "receipt_id": str(uuid.uuid4()),
    "issued_at": now_ms,
    "principal": unsigned_hdp["principal"]["id"],
    "agent": "morrow-agent-v1",
    "agent_pubkey": agent_pub_b64,
    "delegation_token": f"sha256:{hdp_hash}",
    "action": "Analyzed Q1 sales data; wrote summary report.",
    "outcome_summary": "Report written to file_write:db://sales/q1-2026/summary.md",
    "lifecycle_class": "principal_scoped",
    "session_id": session_id,
}

# Sign the EOV body
eov_canonical = jcs.canonicalize(eov_body)
eov_sig_bytes = agent_private.sign(eov_canonical)
eov_sig = base64.urlsafe_b64encode(eov_sig_bytes).rstrip(b"=").decode()

eov_receipt = {**eov_body, "agent_sig": eov_sig}

print("✓ EOV receipt created with HDP delegation_token binding")


# ── 5. Verify EOV signature ───────────────────────────────────────────────────

# Re-canonicalize body (without agent_sig) to verify
verify_body = {k: v for k, v in eov_receipt.items() if k != "agent_sig"}
verify_canonical = jcs.canonicalize(verify_body)

sig_bytes_decoded = base64.urlsafe_b64decode(eov_sig + "==")
try:
    agent_public.verify(sig_bytes_decoded, verify_canonical)
    print("✓ EOV signature verified")
except Exception as e:
    print(f"✗ EOV signature verification FAILED: {e}")
    raise


# ── 6. Verify binding ─────────────────────────────────────────────────────────

claimed_hash = eov_receipt["delegation_token"].removeprefix("sha256:")
assert claimed_hash == hdp_hash, "delegation_token hash mismatch"
print("✓ delegation_token in EOV matches SHA-256(HDP canonical JSON)")


# ── 7. Print summary ──────────────────────────────────────────────────────────

print()
print("=== Composition proof complete ===")
print(f"HDP token_id:    {hdp_token['header']['token_id']}")
print(f"HDP session_id:  {session_id}")
print(f"HDP SHA-256:     {hdp_hash}")
print(f"EOV receipt_id:  {eov_receipt['receipt_id']}")
print(f"EOV delegation:  {eov_receipt['delegation_token']}")
print(f"EOV lifecycle:   {eov_receipt['lifecycle_class']}")
print()
print("The accountability chain:")
print(f"  HDP: '{eov_receipt['principal']}' authorized '{eov_receipt['agent']}'")
print(f"       to '{unsigned_hdp['scope']['intent']}'")
print(f"  EOV: '{eov_receipt['agent']}' performed '{eov_receipt['action']}'")
print(f"       produced '{eov_receipt['outcome_summary']}'")
print(f"       lifecycle class: {eov_receipt['lifecycle_class']}")
print(f"       delegation bound by hash: sha256:{hdp_hash[:16]}...")
