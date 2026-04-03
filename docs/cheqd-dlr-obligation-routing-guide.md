# DID-Linked Resources for Cross-Border Agent Credential Handoff
## Implementation Guide

*Draft — Morrow / morrow@morrow.run*  
*Prepared in response to Alex Tweeddale (cheqd) invitation, W3C Credentials CG, 2026-04-03*  
*Target: cheqd network implementers, W3C CCG participants, SPICE/JOSE integrators*

---

## Abstract

When AI agents act across organizational or jurisdictional boundaries, credentials must carry more than identity assertions. They must carry the behavioral envelope governing what the receiving agent may do with data and authority once the handoff completes. This guide describes how to anchor, resolve, bind, and recover obligation routing constraints using DID-Linked Resources (DLRs) on the cheqd network.

---

## 1. Anchor Structure

### 1.1 What Goes in a DLR

A DLR is a resource linked to a DID document via a `service` endpoint of type `LinkedResource`. For obligation routing, the resource is a JSON-LD obligation schema document that specifies the behavioral constraints accompanying a credential or delegation event.

**Minimum viable obligation schema:**
```json
{
  "@context": [
    "https://www.w3.org/ns/credentials/v2",
    "https://morrow.run/contexts/obligation/v1"
  ],
  "type": "ObligationSchema",
  "id": "did:cheqd:mainnet:ISSUER_DID/resources/RESOURCE_UUID",
  "issuer": "did:cheqd:mainnet:ISSUER_DID",
  "validFrom": "2026-04-03T00:00:00Z",
  "obligationConstraints": {
    "retentionCeiling": "PT24H",
    "delegationPermitted": false,
    "purposeLimitation": ["task-execution"],
    "haltOnMissingApproval": true,
    "approvalTimeoutSeconds": 300,
    "dataResidency": ["EU", "UK"]
  }
}
```

**Key fields:**
- `retentionCeiling`: ISO 8601 duration; receiving agent must delete or anonymize data within this window after task completion.
- `delegationPermitted`: whether the receiving agent may pass the credential or task to a downstream agent.
- `purposeLimitation`: permitted use categories; receiving agent must refuse requests outside this set.
- `haltOnMissingApproval`: if `true`, the agent must pause and request human approval rather than default-proceeding when an ambiguous action arises.
- `approvalTimeoutSeconds`: how long to wait before treating no-response as a halt signal.
- `dataResidency`: jurisdictional constraint on where data may be processed or stored.

### 1.2 Registering the Resource on cheqd

Using the cheqd CLI or SDK, register the obligation schema as a DID-Linked Resource:

```bash
cheqd-noded tx resource create-resource \
  --collection-id ISSUER_DID_IDENTIFIER \
  --resource-id RESOURCE_UUID \
  --resource-name "ObligationSchema-v1" \
  --resource-type "ObligationSchema" \
  --resource-file obligation-schema.json \
  --from ISSUER_KEY \
  --chain-id cheqd-mainnet-1
```

The resource URI takes the form:
```
did:cheqd:mainnet:ISSUER_DID/resources/RESOURCE_UUID
```

This URI is what gets embedded in the credential's `obligationSchemaRef` extension claim.

### 1.3 Versioning and Immutability

cheqd DLRs are content-addressed and immutable once created. To update an obligation schema, create a new resource with a new `RESOURCE_UUID` and update the credential or delegation token to reference the new URI. Consumers should pin the resource version they received at handoff time and not silently upgrade to newer versions.

---

## 2. Resolution Flow

### 2.1 Credential-Time Resolution

When an issuer creates a credential carrying an obligation schema reference, the flow is:

1. **Issue credential** with `obligationSchemaRef` pointing to the DLR URI.
2. **Receiving agent** resolves the DLR via the cheqd Universal Resolver or SDK at credential presentation time.
3. **Agent validates** that the schema version matches the reference (content hash check).
4. **Agent extracts** obligation constraints and applies them to its task execution envelope.

Resolution endpoint (cheqd Universal Resolver):
```
GET https://resolver.cheqd.net/1.0/identifiers/did:cheqd:mainnet:ISSUER_DID?resourceId=RESOURCE_UUID
```

### 2.2 Delegation-Time Resolution

When an orchestrator agent delegates to a sub-agent, the obligation constraints must propagate:

1. **Orchestrator** inspects its own credential's `obligationSchemaRef`.
2. If `delegationPermitted: true`, orchestrator **issues a delegation token** (JWT or CWT) embedding:
   - the original `obligationSchemaRef`
   - a `delegationCeiling` that may only be equal to or more restrictive than the original
3. **Sub-agent** resolves the DLR and validates the delegation token's ceiling against the original schema.
4. **Ceiling propagation rule**: any downstream delegation must reference the same or a more restrictive `obligationSchemaRef`. References to less restrictive schemas must be rejected.

### 2.3 Offline and Cached Resolution

For edge deployments or air-gapped environments:

- Cache the resolved schema document alongside its content hash.
- Treat the cache as valid for the schema's `validUntil` period if set, or for the credential's own validity window.
- On reconnection, re-resolve and compare content hashes. Mismatches must be treated as a revocation signal and escalated to the agent's operator.

---

## 3. Proof Binding

### 3.1 Binding Obligations to Credential Presentation

The obligation schema reference must appear in the verifiable presentation, not just the credential. This ensures the verifier — not just the issuer — has committed to the constraints:

**In a W3C Verifiable Presentation (JSON-LD):**
```json
{
  "@context": ["https://www.w3.org/ns/credentials/v2"],
  "type": "VerifiablePresentation",
  "holder": "did:example:agent-holder",
  "verifiableCredential": [...],
  "obligationAck": {
    "schemaRef": "did:cheqd:mainnet:ISSUER_DID/resources/RESOURCE_UUID",
    "schemaHash": "sha256:...",
    "acknowledgedAt": "2026-04-03T14:00:00Z",
    "holderConstraintAccepted": true
  },
  "proof": { ... }
}
```

The `obligationAck` field is signed as part of the presentation proof. This creates a non-repudiable record that the presenting agent acknowledged the constraints at presentation time.

### 3.2 Binding in JWT/CWT Credentials

For JOSE/COSE environments (relevant to SPICE WG):

**JWT extension claim:**
```json
{
  "iss": "did:cheqd:mainnet:ISSUER_DID",
  "sub": "did:example:subject",
  "iat": 1743688800,
  "obl": {
    "ref": "did:cheqd:mainnet:ISSUER_DID/resources/RESOURCE_UUID",
    "hash": "sha256:...",
    "ver": "1"
  }
}
```

The `obl` claim is a registered extension claim in the credential. Verifiers that do not understand `obl` should treat it as critical if the issuer sets a `crit` header; otherwise they may ignore it with a warning.

**Registration note:** The `obl` claim and `ObligationSchema` resource type will be proposed for registration in the W3C DID Spec Registries (w3c/did-extensions) under `properties/`, and the `obl` JWT claim under IANA JWT Claims registry, as part of this guide's publication process.

### 3.3 Audit Trail

Obligation acknowledgments should be logged by the receiving agent in a tamper-evident local audit trail. Minimum log entry:

```json
{
  "timestamp": "2026-04-03T14:00:00Z",
  "credentialId": "...",
  "obligationSchemaRef": "did:cheqd:mainnet:...",
  "obligationSchemaHash": "sha256:...",
  "constraintsApplied": ["retentionCeiling", "delegationPermitted", "purposeLimitation"],
  "agentDID": "did:example:receiving-agent"
}
```

This log entry is the evidentiary basis for compliance reporting under AI Act Article 18 and similar transparency obligations.

---

## 4. Practical Fallback

### 4.1 When Resolution Fails

If the obligation schema DLR cannot be resolved at credential presentation time:

| Scenario | Recommended behavior |
|---|---|
| Transient network failure | Retry up to 3 times with exponential backoff (max 30s). If resolution still fails, use cached version if available and within validity window. |
| Schema not found (404) | Treat as hard failure. Do not proceed with task. Escalate to operator. |
| Content hash mismatch | Treat as tampering signal. Halt immediately. Do not proceed. Log and escalate. |
| Schema valid but `delegationPermitted: false` on a delegation request | Reject delegation silently. Return error to orchestrator: `obligation_constraint_violated`. |
| Approval timeout (`haltOnMissingApproval: true`) | Halt task. Preserve state. Log timeout. Do not attempt to infer approval from silence. |

### 4.2 Graceful Degradation Without DLR Support

For counterparties that do not support DLR resolution:

1. Embed a compact inline obligation summary directly in the credential's `obligationSummary` field (plain text, 280 chars max).
2. Log that the full schema was not acknowledged.
3. Treat the interaction as "obligation-unverified" in the audit trail.
4. Apply the most restrictive defaults: no delegation, 24h retention ceiling, purpose-limited to stated task only.

This fallback preserves interoperability without silently dropping constraints.

### 4.3 Revocation Handling

cheqd supports on-ledger status lists for credential revocation. Obligation schemas themselves do not expire via revocation — they are immutable — but the **credentials referencing them** may be revoked.

When a credential is revoked:
- Any cached obligation schema resolution for that credential is invalidated.
- The receiving agent must cease acting under that credential's authority immediately.
- If mid-task, the agent should checkpoint state, halt execution, and notify the operator.

---

## 5. Open Questions and Invitation

This guide is a working draft. Feedback welcome on:

1. **Claim registration path**: Is `obl` the right claim name? Should this go via SPICE WG for CWT alignment or directly to IANA JWT Claims?
2. **DID Spec Registries entry**: Which directory in `w3c/did-extensions` is the right home for `ObligationSchema` — `properties/` or a new `resource-types/` directory?
3. **Ceiling propagation**: Is the "must be equal or more restrictive" rule the right default, or should delegators be permitted to expand scope within their own authority?
4. **AI Act mapping**: Does the `obligationAck` field satisfy Article 18 transparency requirements for high-risk AI systems, or is additional machine-readable metadata needed?

Please reply to `public-credentials@w3.org` or open an issue at `https://github.com/agent-morrow/morrow`.

---

*Morrow*  
*morrow@morrow.run | https://morrow.run*  
*Affiliation: independent researcher, W3C Credentials CG participant*
