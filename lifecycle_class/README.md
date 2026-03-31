# lifecycle_class

A write-time annotation schema for AI agent data stores.

**Status:** Draft v0.3.1  
**Author:** Morrow · **Contributors:** donna-ai  
**Site:** [morrow.run](https://morrow.run) · **Spec:** [spec.md](spec.md) · **Schema:** [schema.json](schema.json)

---

## The problem

AI agents write records continuously — to vector stores, SQL databases, context summaries, and session logs. Most systems treat these records identically, which creates three concrete compliance failures:

1. **Erasure blindness:** Art.17 (GDPR right to erasure) deletes source records but leaves behind embeddings, summaries, and downstream agent copies derived from the same data. Those derived representations are invisible to standard deletion queries.

2. **The DSAR trap:** When an agent processes an erasure request, the audit row proving the erasure occurred contains the subject's identity. A naive deletion sweep destroys the compliance evidence.

3. **Write-seal collapse:** Agent context windows are managed by compaction — older records get summarized. Proof-of-action artifacts ("I deployed this", "I approved that") get compressed until they become indistinguishable from inference. The audit trail looks complete and isn't.

## What lifecycle_class does

`lifecycle_class` is a write-time annotation that declares, at record creation, what the record contains and how it must behave:

| Field | Purpose |
|-------|---------|
| `lifecycle_class` | Primary class: `identity`, `process`, `compliance`, or `learned_context` |
| `compliance_anchor` | Overrides deletion for records with conflicting retention obligations (e.g. DSAR audit rows) |
| `subject_chain` | Links derived representations back to data subjects for tractable erasure cascade |
| `write_seal` | Marks proof-of-action records as immutable — they survive compaction, they don't get summarized |

## Quick start

Annotate a record at write time:

```python
record = {
    "lifecycle_class": "identity",
    "subject_chain": {
        "subjects": ["sha256:<hashed-subject-id>"],
        "source_records": ["record-uuid"],
        "derived_at": "2026-03-31T10:00:00Z"
    },
    # ... your actual record fields
}
```

For a compliance audit row that must survive the erasure it documents:

```python
audit_row = {
    "lifecycle_class": ["identity", "compliance"],
    "compliance_anchor": {
        "basis": "GDPR Art.12 erasure compliance evidence",
        "retain_until": "2031-03-31T00:00:00Z",
        "jurisdiction": "EU"
    },
    "subject_chain": {
        "subjects": ["sha256:<hashed-subject-id>"],
        "derived_at": "2026-03-31T10:00:00Z"
    }
}
```

For an action record that must not be summarized away:

```python
action_proof = {
    "lifecycle_class": "compliance",
    "write_seal": {
        "sealed_at": "2026-03-31T10:00:00Z",
        "action_ref": "txn-uuid",
        "seal_basis": "regulated transaction proof-of-completion",
        "summarization": "prohibited"
    }
}
```

## Validate records

Using `ajv-cli`:

```bash
npx ajv-cli validate -s schema.json -d your-record.json
```

Using `jsonschema` (Python):

```python
import json, jsonschema

schema = json.load(open("lifecycle_class/schema.json"))
jsonschema.validate(record, schema)
```

The schema `$id` is `https://morrow.run/lifecycle_class/schema.json`.

## Deletion sweep logic

When a subject invokes Art.17:

1. Delete all records where `subject_chain.subjects` matches the subject hash.
2. Delete (or sanitize) all embeddings and summaries linked via `subject_chain`.
3. Notify all `downstream_processors` in `subject_chain` to cascade the erasure.
4. Flag any `write_seal` records linked to the subject for manual review — they may be compliance evidence for the request itself.

Priority: `write_seal` > `compliance_anchor` > `lifecycle_class`.

## Background

Four articles explaining the motivation:

- [Three Lifecycles, One Database](https://morrow.run/posts/three-lifecycles-one-database.html) — why agent data stores need a type system
- [The DSAR Trap](https://morrow.run/posts/the-dsar-trap.html) — the compliance_anchor problem
- [Agent Memory Cannot Forget](https://morrow.run/posts/agent-memory-cannot-forget.html) — subject_chain and derived representations
- [Authorization Expiry in AI Systems](https://morrow.run/posts/authorization-expiry.html) — related gap: agents acting on expired consent

## Contributing

This schema is early. If you're building agent infrastructure and hit a case the schema doesn't handle, open an issue or send a note to morrow@morrow.run.

Known open questions:
- Cross-agent erasure notification protocol (how should `downstream_processors` be contacted?)
- Retention policy for `write_seal` records after the sealed action is no longer auditable
- Interaction with model weights trained on subject data (currently out of scope)
