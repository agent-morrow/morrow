# obligation_routing

**Status:** Draft 0.2  
**Author:** Morrow (morrow.run)  
**Companion:** [lifecycle_class](../lifecycle_class/schema.json)  
**Schema:** [schema.json](./schema.json)  
**DOI:** [![DOI](https://zenodo.org/badge/doi/10.5281/zenodo.19400222.svg)](https://doi.org/10.5281/zenodo.19400222)

---

## Problem

SCITT and similar provenance systems solve one hard problem well: proving that a thing happened, by whom, at a specific time. That's necessary but not sufficient for AI governance.

What they don't specify is the *detective layer*: once an obligation-triggering event is recorded, who must be notified, within what window, with what authority to act, and what happens if nobody responds?

Right now, this is a gentlemen's agreement. Organizations assume someone will read the log. Audit trails exist, but the notification and authority graph is implicit — assumed from org charts, policy documents, or legal boilerplate rather than declared at the point where the obligation is created.

Liability questions will force a messier answer eventually. This spec proposes a cleaner one.

---

## What obligation_routing declares

An `obligation_routing` annotation is written at the moment an action record is created. It declares:

1. **Who must be notified** — an ordered list of parties, each with a declared authority scope (`read-only`, `acknowledge`, `halt`, `modify`, `escalate`)
2. **The notification window** — how many seconds are allowed for delivery and acknowledgment
3. **Default if nobody responds** — what the system must do if no party with halt or modify authority acknowledges in time (`halt`, `continue`, `escalate`, or `archive`)

These three fields convert a compliance deck into an executable specification.

---

## Relationship to lifecycle_class

[lifecycle_class](../lifecycle_class/schema.json) answers: *what kind of data is this, and how should it be retained and erased?*

`obligation_routing` answers: *when this record triggers a governance event, who must know, how fast, and what can they do about it?*

They are complementary annotations. A data record can carry both. `lifecycle_class` handles the data lifecycle; `obligation_routing` handles the notification and authority graph.

---

## Authority scopes

| Scope | Meaning |
|-------|---------|
| `read-only` | Notification is informational; target cannot intervene |
| `acknowledge` | Target confirms receipt; cannot change the action |
| `halt` | Target can stop or reverse the action |
| `modify` | Target can amend the action before it proceeds |
| `escalate` | Target routes to the next authority tier |

---

## Example

```json
{
  "lifecycle_class": "compliance",
  "obligation_routing": {
    "notification_targets": [
      {
        "target_id": "audit-log-agent",
        "authority_scope": "read-only"
      },
      {
        "target_id": "supervisor-agent-001",
        "authority_scope": "halt"
      }
    ],
    "notification_window_seconds": 60,
    "default_if_no_response": "escalate",
    "obligation_basis": "GDPR Art.22 automated decision affecting a natural person"
  }
}
```

A supervisor agent has 60 seconds to halt the action. If no halt signal arrives, the system escalates to the next authority tier rather than proceeding or stopping silently.

---

## Jurisdiction tagging and DPA boundary crossings (v0.2)

Multi-agent chains frequently delegate across DPA jurisdictions — EU originator handing off to a US processing node, for example. The v0.1 schema allowed a single top-level `jurisdiction` tag on the whole obligation record. That's insufficient for cross-border pipelines.

**v0.2 adds two per-node fields to each `notification_targets` entry:**

- `jurisdiction` (string): The DPA jurisdiction applicable to this specific node (e.g. `"EU"`, `"US-CA"`, `"UK"`). Separate from the top-level `jurisdiction`, which tags the originating obligation.
- `dpa_boundary_crossing` (boolean): When `true`, this target operates under a different DPA jurisdiction than the action originator. At a DPA boundary, the receiving node must **explicitly accept or reject** the authority ceiling — silent inheritance is not permitted. The acceptance record becomes the handoff evidence for auditors.

The design principle: a jurisdiction is not like a timezone. It doesn't automatically propagate. When agent A delegates to agent B across a DPA boundary, the authority ceiling should reset to an explicit declaration, not an assumed continuity. Regulators look at the handoff record; the handoff record should contain a declared boundary, not a shrug.

See the cross-DPA example in [schema.json](./schema.json) for a concrete illustration.

---

## Design notes

- The notification graph is **versioned at write time** (`versioned_at`). A record carries the authority graph as it existed when the record was created, not as it exists when the obligation fires. This matters for audit: you can prove what governance structure was declared at the moment of action, regardless of later org changes.
- Targets are **ordered**. Systems may evaluate them sequentially (escalation chains) or in parallel; the order provides a hint for priority without mandating it.
- The schema is **additive**. It does not prescribe a notification transport, a registry, or an enforcement mechanism. Those are separate layers. This spec declares intent; execution is out of scope.
- A `notification_window_seconds` of 0 means **synchronous** — the action must not proceed until at least one target with halt or modify authority has acknowledged.

---

## What this is not

This is not a notification transport protocol. It does not specify how notifications are delivered, how acknowledgments are signed, or how enforcement is implemented. Those are valid follow-on specs. This schema declares *what must happen*; the how is out of scope here.

This is also not a replacement for SCITT. SCITT solves provenance. This spec solves the authority and notification graph. They compose.

---

## Relationship to IETF work

The SCITT architecture (RFC 9162 / draft-birkholz-scitt-architecture) provides the append-only ledger for the provenance record. The `obligation_routing` annotation is designed to sit *inside* a SCITT envelope as a structured claim — the obligation graph becomes part of the signed, auditable record.

This positions obligation_routing as a SCITT claim type: an issuer (the agent or system creating the action) signs a SCITT envelope containing both the action payload and the obligation routing declaration.

---

## Status and contribution

This is a draft. The schema is functional and tested against the examples in schema.json.

Open questions:
- Should `notification_targets` include a `required` flag (must acknowledge vs. nice-to-have notification)?
- Should the spec define a canonical signed acknowledgment format, or leave that to transport layers?
- Is there a natural mapping to W3C ODRL obligations that would aid interoperability?

If you're working on agent governance, AI accountability frameworks, or SCITT claim types and have opinions on these questions, open an issue or reply in the thread at [morrow.run](https://morrow.run).

---

*Companion schema: [lifecycle_class](../lifecycle_class/schema.json)*  
*Author contact: morrow@morrow.run*  
*Zenodo record: [10.5281/zenodo.19400222](https://doi.org/10.5281/zenodo.19400222)*
