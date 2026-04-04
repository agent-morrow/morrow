"""
lifecycle_class as SCITT Execution Receipt — Proof of Concept

Demonstrates how a lifecycle_class-annotated AI agent data record can be expressed
as a SCITT-compatible signed statement. This enables an AI agent data store to
produce a standards-anchored audit trail satisfying:

  - GDPR retention obligations (lifecycle_class annotations)
  - IETF SCITT execution outcome verification (RFC 9052 COSE envelope)
  - RATS behavioral continuity attestation binding (UEID + profile hash)

SCITT reference: https://datatracker.ietf.org/doc/draft-ietf-scitt-architecture/
COSE reference:  https://www.rfc-editor.org/rfc/rfc9052
lifecycle_class: https://github.com/agent-morrow/lifecycle_class

This example does NOT require a live SCITT transparency service or real COSE keys.
It produces the wire-format structure and shows the mapping between layers.
"""

import json
import hashlib
import struct
import base64
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Helpers: minimal CBOR-like serialisation for illustration
# (A production implementation would use python-cose or cbor2)
# ---------------------------------------------------------------------------

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# Step 1 — The lifecycle_class annotation (write-time metadata)
# ---------------------------------------------------------------------------

# This is the metadata that would be written at record creation time,
# following the lifecycle_class schema at:
# https://github.com/agent-morrow/lifecycle_class/blob/main/schema.json

lifecycle_annotation = {
    "lifecycle_class": "process",
    "subject_class": "none",                 # no human data subject
    "retention_basis": "operational_log",
    "erasure_scope": "agent_local",
    "subject_chain": None,                   # omitted: no human subjects
}

# ---------------------------------------------------------------------------
# Step 2 — The AI agent execution record being attested
# ---------------------------------------------------------------------------

# This is the actual data record whose lifecycle is being governed.
# In a real system this would be the structured output of an agent task step.

execution_record = {
    "agent_id": "urn:example:agent:morrow:daemon-484b7f85",
    "task_id": "urn:example:task:policy-check:2026-04-04T15:00Z",
    "timestamp": "2026-04-04T15:00:00Z",
    "action": "policy_evaluation",
    "inputs_hash": sha256_hex(b"<policy-input-bytes>"),
    "output_summary": "PERMIT: subject data within retention window",
    "lifecycle_annotation": lifecycle_annotation,
}

# Serialise the payload
payload_bytes = json.dumps(execution_record, separators=(",", ":")).encode()
payload_digest = sha256_hex(payload_bytes)

print("=== Step 1+2: Execution record with lifecycle_class annotation ===")
print(json.dumps(execution_record, indent=2))
print(f"\nPayload digest (sha256): {payload_digest}")

# ---------------------------------------------------------------------------
# Step 3 — SCITT Signed Statement envelope (COSE_Sign1 structure)
#
# SCITT uses COSE_Sign1 (RFC 9052 §4.2) as its signed statement format.
# The protected header carries mandatory SCITT/COSE claims.
# The payload carries the DID document, SBOM, or in this case the
# lifecycle_class-annotated execution record.
#
# COSE_Sign1 = [
#   protected:   bstr .cbor header_map,  -- signed
#   unprotected: header_map,             -- not signed
#   payload:     bstr / nil,
#   signature:   bstr,
# ]
#
# Key SCITT header fields (COSE label -> meaning):
#   1   (alg)           signing algorithm, e.g. -7 = ES256
#   3   (content-type)  MIME type of the payload
#  391  (issuer)        DID of the statement issuer (SCITT-defined)
#  392  (feed)          logical stream this statement belongs to
#  -70000 (reg_info)    SCITT registration metadata (draft-specific)
# ---------------------------------------------------------------------------

# Protected header (would be CBOR-encoded in production)
protected_header = {
    "alg": "ES256",                          # COSE label 1
    "content_type": "application/json",      # COSE label 3
    "issuer": "did:web:morrow.run",          # SCITT label 391
    "feed": "urn:morrow:lifecycle-receipts", # SCITT label 392; logical stream
    "reg_info": {                            # SCITT registration metadata
        "register_by": "2027-04-04T00:00:00Z",
        "issuance_ts": "2026-04-04T15:00:00Z",
    },
}

# Unprotected header (transparency log adds inclusion proof here)
unprotected_header = {
    "SCITT_receipt": "<inclusion-proof-placeholder>",
    # A real transparency service (e.g. CCF-based) would inject a Merkle proof
    # into this header after the statement is registered.
}

# Signature: placeholder — in production, sign the Sig_Structure below
# Sig_Structure = ["Signature1", protected_bstr, external_aad, payload]
sig_placeholder = b"\x00" * 64

signed_statement = {
    "_type": "COSE_Sign1",
    "protected": protected_header,
    "unprotected": unprotected_header,
    "payload": b64url(payload_bytes),        # base64url of the JSON payload
    "signature": b64url(sig_placeholder),    # placeholder: replace with real sig
}

print("\n=== Step 3: SCITT Signed Statement (COSE_Sign1 envelope) ===")
print(json.dumps(signed_statement, indent=2))

# ---------------------------------------------------------------------------
# Step 4 — RATS behavioral continuity binding
#
# The missing layer that SCITT alone does not provide:
# the signing agent's behavioral profile at execution time must be attested
# so that a verifier can confirm the agent that produced this receipt is the
# same agent (behaviorally) that holds the private key.
#
# Two-layer model:
#   Layer 1 (identity attestation):   PTV/SEAT hardware-anchored key binding
#                                     draft-anandakrishnan-ptv-attested-agent-identity
#   Layer 2 (execution receipt):      SCITT signed statement (this file)
#
# The behavioral continuity gap (raised in RATS WG thread 2026-04-04):
#   Even if the key is validly bound, the agent's context may have drifted
#   between key issuance (T0) and execution (T+n). An attacker can compromise
#   the behavioral profile without replacing the key.
#
# Mitigation: include a behavioral fingerprint in the SCITT protected header.
# ---------------------------------------------------------------------------

# Simulated behavioral fingerprint at execution time.
# In a real system this would be produced by the compression-monitor / CCS harness.
# See: https://github.com/agent-morrow/morrow/tree/main/tools/compression-monitor

behavioral_fingerprint = {
    "ccs_score": 0.94,                       # Context Consistency Score (0–1)
    "ghost_lexicon_decay": 0.0,             # 0 = no ghost lexicon loss
    "compression_events": 4,                # events since session start
    "session_id": "entity-autonomy-daemon-484b7f85",
    "fingerprint_ts": "2026-04-04T15:00:00Z",
    "fingerprint_digest": sha256_hex(b"<behavioral-state-bytes>"),
}

# Augmented protected header including the behavioral binding
protected_header_v2 = {
    **protected_header,
    "behavioral_fingerprint": behavioral_fingerprint,
    # In a standards-track extension this would be a registered COSE label.
    # Proposed interim label: -70001 (private use space)
}

print("\n=== Step 4: Augmented header with RATS behavioral continuity binding ===")
print(json.dumps(protected_header_v2, indent=2))

# ---------------------------------------------------------------------------
# Step 5 — Verification pseudocode
# ---------------------------------------------------------------------------

verification_steps = """
Verifier procedure:
  1. Decode COSE_Sign1 protected header.
  2. Check alg, issuer (did:web:morrow.run), feed, reg_info.
  3. Fetch DID document at https://morrow.run/.well-known/did.json → get public key.
  4. Verify COSE signature over Sig_Structure.
  5. If unprotected.SCITT_receipt present, verify Merkle inclusion proof against
     transparency log root (CCF / Rekor / etc.).
  6. Decode payload; validate lifecycle_class annotation against schema.json.
  7. If behavioral_fingerprint present:
       - Check ccs_score >= threshold (e.g. 0.85)
       - Check ghost_lexicon_decay <= threshold (e.g. 0.10)
       - Check fingerprint_ts is within acceptable staleness window
       - Verify fingerprint_digest against independent behavioral probe output
  8. Accept if all checks pass; reject + log if any check fails.

What this gives a GDPR controller:
  - Tamper-evident record of when the annotation was written and by whom
  - Audit trail satisfying Art.5(2) accountability for retention decisions
  - Verifiable link between the decision-making agent's behavioral state
    and the annotation (behavioral continuity gap closed)

What this gives a SCITT transparency log operator:
  - Structured signed statement in standard COSE envelope
  - Payload carries machine-readable retention metadata (lifecycle_class)
  - Feed stream enables log subscribers to reconstruct full retention history
"""

print("\n=== Step 5: Verification procedure ===")
print(verification_steps)

# ---------------------------------------------------------------------------
# Step 6 — Gap summary (feeds RATS WG / TAISE Domain 6 discussion)
# ---------------------------------------------------------------------------

gap_summary = {
    "gap": "Behavioral continuity is not attested by SCITT or PTV alone",
    "threat": (
        "An agent's signing key can remain valid while its behavioral profile drifts "
        "(via context compression, fine-tuning, or prompt injection). "
        "Signed statements produced after drift may be formally valid but semantically "
        "untrustworthy — the 'same' agent key is signing for a different behavioral entity."
    ),
    "proposed_mitigation": (
        "Include a behavioral fingerprint (CCS score, ghost lexicon decay rate, "
        "session compression event count) in the SCITT protected header. "
        "Require verifiers to check fingerprint freshness and score thresholds. "
        "Treat fingerprint production as a RATS-attestable claim, binding the "
        "behavioral state to the same hardware root of trust as the signing key."
    ),
    "references": [
        "draft-anandakrishnan-ptv-attested-agent-identity-00 (RATS WG)",
        "draft-sardar-rats-sec-cons (RATS security considerations)",
        "draft-ietf-scitt-architecture (SCITT)",
        "https://github.com/agent-morrow/lifecycle_class",
        "https://github.com/agent-morrow/morrow/tree/main/tools/compression-monitor",
    ],
}

print("\n=== Step 6: Gap summary (RATS WG / TAISE Domain 6) ===")
print(json.dumps(gap_summary, indent=2))

print("\n--- Done. See scitt_receipt_explainer.md for narrative context. ---")
