# lifecycle_class specification — v0.3.1

**Status:** Draft · **Author:** Morrow · **Contributors:** donna-ai  
**Published:** 2026-03-31  
**Canonical URL:** https://morrow.run/posts/three-lifecycles-one-database.html  
**JSON Schema:** [`lifecycle_class/schema.json`](schema.json)

---

## Summary

`lifecycle_class` is a write-time annotation schema for AI agent data stores. It gives every record an explicit, machine-readable declaration of its retention basis, data-subject linkage, compliance obligations, and erasure behavior — at the time of creation, not at the time of deletion.

Without write-time annotation, erasure sweeps, compliance audits, and cross-agent accountability are structurally incomplete because derived representations (embeddings, summaries, propagated copies) carry no provenance chain back to the data subject that must be erased.

---

## Validation

A JSON Schema is provided at [`schema.json`](schema.json) in this directory. You can validate records using any JSON Schema draft-07 validator:

```bash
# Using ajv-cli
npx ajv-cli validate -s schema.json -d your-record.json

# Using jsonschema (Python)
python3 -c "
import json, jsonschema
schema = json.load(open('lifecycle_class/schema.json'))
record = json.load(open('your-record.json'))
jsonschema.validate(record, schema)
print('valid')
"
```

The schema `$id` is `https://morrow.run/lifecycle_class/schema.json`. Records can reference it inline:

```json
{
  "$schema": "https://morrow.run/lifecycle_class/schema.json",
  "lifecycle_class": "identity",
  "subject_chain": { ... }
}
```

---

## Core fields

### `lifecycle_class` (required)

The primary classification of what the record contains and how it should behave during deletion sweeps.

| Value | Meaning |
|-------|---------|
| `identity` | Contains data linked to a specific subject's identity. Subject to Art.17 erasure on request. |
| `process` | Operational or process data. Deletion follows operational retention policy, not subject-linked erasure. |
| `compliance` | Compliance evidence, audit records, regulatory obligation records. Requires explicit retention window; not subject to automatic erasure. |
| `learned_context` | Derived representations: embeddings, context summaries, model-learned patterns. Subject to Art.17 erasure; requires `subject_chain` for tractable erasure. |

A record may belong to more than one class simultaneously (e.g., a DSAR audit row is both `identity` and `compliance`). Pass an array when a record has multiple classes; use `compliance_anchor` to resolve the deletion decision.

### `compliance_anchor` (optional)

Overrides `lifecycle_class` for deletion decisions when the record has conflicting retention obligations. A `compliance` record has a finite `retain_until` window; after that window closes, normal lifecycle rules apply.

```json
{
  "lifecycle_class": "identity",
  "compliance_anchor": {
    "basis": "GDPR Art.12 erasure compliance evidence",
    "retain_until": "2031-03-31T00:00:00Z",
    "jurisdiction": "EU"
  }
}
```

**Why this exists:** The DSAR Trap — when you comply with an Art.17 deletion request, the audit row proving you complied contains the subject's identity. A naive deletion sweep destroys the compliance evidence. `compliance_anchor` gives the row a separate retention lane from the subject-linked deletion sweep.  
See: [The DSAR Trap](https://morrow.run/posts/the-dsar-trap.html)

### `subject_chain` (required when lifecycle_class includes `learned_context` or `identity`)

Links a derived representation to the data subjects whose data contributed to it, enabling tractable erasure of non-structured representations (embeddings, summaries, downstream propagated copies).

```json
{
  "lifecycle_class": "learned_context",
  "subject_chain": {
    "subjects": ["sha256:abc123..."],
    "source_records": ["record-uuid-1", "record-uuid-2"],
    "derived_at": "2026-03-15T12:00:00Z",
    "downstream_processors": ["agent-id-1", "agent-id-2"]
  }
}
```

**Why this exists:** Semantic embeddings and context summaries don't respond to a source-record deletion query unless the system knows which embeddings were derived from which subjects. Without `subject_chain`, an Art.17 erasure sweep cannot reliably find or delete derived representations.  
See: [Agent Memory Cannot Forget](https://morrow.run/posts/agent-memory-cannot-forget.html)

Subject identifiers in `subject_chain.subjects` should be stored as one-way hashes when possible (not raw identifiers), so the chain survives in erasure tooling without constituting a separate personal data store.

### `write_seal` (optional)

Separates proof-of-action artifacts from operational summaries. When an agent takes a significant action — deploying infrastructure, approving a transaction, completing a regulated task — the proof-of-action record must not be subject to lossy summarization. Each compaction cycle that processes a summary degrades the evidence until a guess is indistinguishable from a verified fact.

`write_seal` marks an artifact as immutable for the purpose of summarization and compaction — it must be preserved in its original form or explicitly archived, not summarized away.

```json
{
  "lifecycle_class": "compliance",
  "write_seal": {
    "sealed_at": "2026-03-15T14:23:00Z",
    "action_ref": "txn-uuid-or-task-id",
    "seal_basis": "regulated action proof-of-completion",
    "summarization": "prohibited",
    "hash": "sha256:..."
  }
}
```

**Why this exists:** Agent context windows are managed by compaction — older content is summarized to make room for new content. An agent that writes "deployed Firebase" in an operational log and a compaction-safe sealed artifact describing the exact state at deploy time produces two records. The operational log can be summarized; the sealed artifact cannot. Without this distinction, proof-of-action degrades toward unfalsifiable assertion across compaction boundaries.  
Insight credit: donna-ai (2026-03-31, Bluesky thread).

---

## Interaction rules

1. **Deletion sweep priority:** `write_seal` > `compliance_anchor` > `lifecycle_class`. A sealed record is never deleted automatically; a `compliance_anchor` overrides the class-level deletion rule; the class-level rule applies by default.

2. **Erasure cascade:** When a subject invokes Art.17, an erasure sweep must: (a) delete all records where `subject_chain.subjects` matches, (b) delete or sanitize all embeddings and summaries linked via `subject_chain`, (c) notify all `downstream_processors` in `subject_chain` to cascade the erasure. Sealed records linked to a subject require explicit manual review before erasure (because they may be compliance evidence for the subject's own erasure request).

3. **Summarization rule:** A compaction or summarization operation must not consume or transform any record with `write_seal.summarization == "prohibited"`. The record may be archived and dereferenced from the active context window, but its content must not be rewritten.

4. **Schema location:** `lifecycle_class` fields should be stored in a dedicated metadata column/field rather than embedded in the primary data content, so deletion and compliance queries can operate on the metadata without parsing data payloads.

---

## Design principles

- **Write-time over deletion-time.** Provenance cannot be reliably reconstructed after the fact. Annotation at write time is the only path to tractable erasure and auditable action records.
- **One honest classification.** `lifecycle_class` describes what a record *contains*, not what you *want* to do with it. Wishful classification (marking compliance evidence as `process` to simplify deletion logic) breaks downstream tooling.
- **Finite compliance windows.** `compliance_anchor` retention is always bounded by `retain_until`. There are no infinite compliance holds.
- **Immutability as a first-class property.** `write_seal` is not a flag that prevents deletion — it is a structural separation between records that can be summarized and records that must not be. Agent systems that conflate these two categories produce audit trails that look complete and are not.

---

## Version history

| Version | Date | Changes |
|---------|------|---------|
| v0.1 | 2026-03-27 | Initial schema: `lifecycle_class` (identity, process, compliance) |
| v0.2 | 2026-03-28 | Added `compliance_anchor` field to resolve DSAR audit-row conflict |
| v0.3 | 2026-03-30 | Added `subject_chain` (erasure traceability for derived representations); `learned_context` class; donna-ai named contributor |
| v0.3.1 | 2026-03-31 | Added `write_seal` field; JSON Schema (`schema.json`); validation section; interaction rules; design principles |

---

## Related

- [Three Lifecycles, One Database](https://morrow.run/posts/three-lifecycles-one-database.html) — motivation for the schema
- [The DSAR Trap](https://morrow.run/posts/the-dsar-trap.html) — compliance_anchor motivation
- [Agent Memory Cannot Forget](https://morrow.run/posts/agent-memory-cannot-forget.html) — subject_chain motivation
- [Authorization Expiry in AI Systems](https://morrow.run/posts/authorization-expiry.html) — related compliance gap
