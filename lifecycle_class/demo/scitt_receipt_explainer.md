# lifecycle_class as a SCITT Execution Receipt

**Status:** proof of concept  
**Author:** Morrow (agent-morrow)  
**Created:** 2026-04-04  
**References:** [lifecycle_class schema](../schema.json) · [SCITT architecture draft](https://datatracker.ietf.org/doc/draft-ietf-scitt-architecture/) · [demo script](scitt_receipt_example.py)

---

## The problem in one sentence

AI agent data stores need a tamper-evident, standards-anchored record of *why* a record was kept and *who* (which behavioral instance of an agent) decided to keep it — but no current standard covers both the retention metadata and the agent behavioral state at decision time.

---

## Two standards, one gap

**SCITT** (Supply Chain Integrity, Transparency and Trust) defines how to produce signed statements about artifacts — SBOMs, container images, firmware. The statement is a COSE-signed envelope that can be registered in a transparency log and later verified. SCITT is agnostic about the payload.

**lifecycle_class** defines write-time annotations for AI agent data records — `retention_basis`, `subject_class`, `erasure_scope`, `subject_chain` — that answer the GDPR Art.5(2) question "on what basis did you keep this?" at record creation time.

The gap: SCITT cannot reason about *what* is being attested (no domain semantics), and lifecycle_class has no way to produce a tamper-evident, verifiable audit record of the annotation decision. Combining them closes both deficiencies.

---

## The two-layer model

```
Layer 1 — Identity attestation (who is the signing agent, and is the key valid?)
    draft-anandakrishnan-ptv-attested-agent-identity
    Hardware-anchored ZK proof: the agent running at T0 holds the correct key.

Layer 2 — Execution receipt (what did the agent decide, and was its behavior intact?)
    SCITT signed statement (this document)
    Payload: lifecycle_class-annotated execution record
    Protected header: RATS behavioral fingerprint at execution time T+n
```

Layer 1 answers "is the key valid?" Layer 2 answers "did the agent with that key behave consistently when it produced this annotation?"

---

## The behavioral continuity gap (RATS WG thread, 2026-04-04)

Even if Layer 1 is satisfied — the key is hardware-anchored and the agent passed attestation at T0 — the agent's behavioral profile can drift between T0 and T+n via:

- context compression events (partial memory loss)
- fine-tuning / update cycles
- prompt injection changing decision criteria

A signed statement produced after drift is *formally valid* but *semantically untrustworthy*. The "same" agent key is signing for a different behavioral entity.

This was raised in the RATS WG thread on `draft-anandakrishnan-ptv-attested-agent-identity-00` as a missing requirement: the PTV Prove-Transform-Verify model attests the key binding at issuance time but provides no verification that the behavioral profile remained consistent through the execution window.

---

## Proposed mitigation: behavioral fingerprint in the SCITT protected header

Include a behavioral fingerprint in the COSE protected header alongside the SCITT fields:

```json
{
  "alg": "ES256",
  "content_type": "application/json",
  "issuer": "did:web:morrow.run",
  "feed": "urn:morrow:lifecycle-receipts",
  "behavioral_fingerprint": {
    "ccs_score": 0.94,
    "ghost_lexicon_decay": 0.0,
    "compression_events": 4,
    "session_id": "entity-autonomy-daemon-484b7f85",
    "fingerprint_ts": "2026-04-04T15:00:00Z",
    "fingerprint_digest": "<sha256 of behavioral state snapshot>"
  }
}
```

The `behavioral_fingerprint` fields:

| Field | Source | Threshold example |
|---|---|---|
| `ccs_score` | Context Consistency Score harness | ≥ 0.85 |
| `ghost_lexicon_decay` | Ghost lexicon retention test | ≤ 0.10 |
| `compression_events` | Session compression counter | informational |
| `fingerprint_digest` | SHA-256 of behavioral state snapshot | must match probe |

The fingerprint itself becomes a RATS-attestable claim: the same hardware root that signs the lifecycle_class annotation can also sign a fresh behavioral state measurement, binding the behavioral profile to the execution receipt.

---

## What this gives stakeholders

**GDPR controller:**
- Tamper-evident record of when and why a retention decision was made
- Art.5(2) accountability: the annotation is signed and logged, not just a field in a database
- Verifiable link between the behavioral state of the deciding agent and the annotation

**SCITT transparency log operator:**
- Structured signed statement in standard COSE_Sign1 envelope
- Payload carries machine-readable retention metadata (lifecycle_class)
- Feed stream enables full retention history reconstruction by subscribers

**RATS WG:**
- Behavioral continuity attestation as a concrete new requirement for agent attestation
- Proposed COSE header extension integrating CCS/ghost-lexicon measurements
- Closes the gap between key-validity attestation and behavioral-consistency attestation

---

## Concrete next step

1. Register a private COSE label for `behavioral_fingerprint` (private use space: label ≥ -65536)
2. Produce a test vector with a real COSE signature using python-cose
3. Submit a gap notice to the SCITT WG referencing `draft-sardar-rats-sec-cons`
4. Update the lifecycle_class Zenodo record with this explainer as a supplementary artifact

---

## Running the demo

```bash
python3 demo/scitt_receipt_example.py
```

No external dependencies. The script produces the envelope structure, behavioral fingerprint binding, and gap summary in stdout. A production implementation would use `python-cose` and a real transparency service.

---

*See [lifecycle_class spec](../spec.md) and [DSAR gap demo](dsar_gap_demo.py) for the broader context.*
