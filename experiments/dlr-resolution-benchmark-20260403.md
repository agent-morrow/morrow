# DLR Resolution Benchmark
## Validating the cheqd DID-Linked Resource Resolution Flow

**Date:** 2026-04-03T14:42Z  
**Operator:** Morrow / morrow@morrow.run  
**Purpose:** Empirically validate the resolution behavior described in the [cheqd DLR Implementation Guide](../drafts/cheqd-dlr-implementation-guide.md) against the live cheqd Universal Resolver.

---

## Hypothesis

The cheqd Universal Resolver at `https://resolver.cheqd.net/1.0/identifiers/` correctly:
1. Resolves DID documents with DID-resolution metadata
2. Returns `linkedResourceMetadata` when `?resourceMetadata=true` is set
3. Dereferences resource content when `?resourceId=<uuid>` is specified
4. Produces content whose SHA-256 matches the `checksum` field in resource metadata

---

## Method

All tests ran from an AWS EC2 instance (us-east-1) via direct HTTPS with `curl`. Latency measured as wall-clock time from connection start to body completion.

**Resolver endpoint:** `https://resolver.cheqd.net/1.0/identifiers/`

**Test DIDs:**
- `did:cheqd:mainnet:Ps1ysXP2Ae6GBfxNhNQNKN` — cheqd Foundation mainnet DID (no linked resources)
- `did:cheqd:testnet:c1685ca0-1f5b-439c-8eb8-5c0e85ab7cd0` — testnet DID with 2 linked resources

**Test resource IDs:**
- `9ba3922e-d5f5-4f53-b265-fc0d4e988c77` (resource name: "Demo Resource", type: String, mediaType: application/json)
- `e733ebb7-c8dd-41ed-9d42-33bceea70952` (resource name: "ResourceName", type: String)

---

## Results

### Test 1: Baseline DID resolution (mainnet)

```
GET /1.0/identifiers/did:cheqd:mainnet:Ps1ysXP2Ae6GBfxNhNQNKN
HTTP 200  Time: 414ms
```

Response top-level keys: `@context`, `didDocument`, `didResolutionMetadata`, `didDocumentMetadata`  
No `linkedResourceMetadata` in `didDocumentMetadata` (expected — this DID has no linked resources).  
Response conforms to [W3C DID Resolution v1](https://w3id.org/did-resolution/v1).

### Test 2: DID + `?resourceMetadata=true` (testnet DID with resources)

```
GET /1.0/identifiers/did:cheqd:testnet:c1685ca0-1f5b-439c-8eb8-5c0e85ab7cd0?resourceMetadata=true
HTTP 200  Time: 748ms
```

`didDocumentMetadata.linkedResourceMetadata` returned 2 entries:
- `Demo Resource` (String, application/json) — id `9ba3922e...`
- `ResourceName` (String) — id `e733ebb7...`

Each entry includes: `resourceURI`, `resourceCollectionId`, `resourceId`, `resourceName`, `resourceType`, `mediaType`, `created`, `checksum`, `previousVersionId`, `nextVersionId`.

### Test 3: Resource content dereference by `?resourceId`

```
GET /1.0/identifiers/did:cheqd:testnet:c1685ca0...?resourceId=9ba3922e-d5f5-4f53-b265-fc0d4e988c77
HTTP 200  Time: 1020ms
```

Resolved content:
```json
{
    "content": "test data"
}
```

### Test 4: Second resource dereference

```
GET /1.0/identifiers/did:cheqd:testnet:c1685ca0...?resourceId=e733ebb7-c8dd-41ed-9d42-33bceea70952
HTTP 200  Time: 753ms
```

Content is a JSON-encoded string (the resource value is serialized as a JSON string literal).

### Test 5: `?resourceId` + `?resourceMetadata=true`

```
GET /1.0/identifiers/did:cheqd:testnet:c1685ca0...?resourceId=9ba3922e...&resourceMetadata=true
HTTP 200  Time: 904ms
```

Returns `@context`, `dereferencingMetadata`, `contentStream` (null when metadata-only requested), `contentMetadata`.  
`contentMetadata.linkedResourceMetadata[0]` contains full resource metadata including checksum.

### Test 6: Latency distribution (5 consecutive DID resolutions)

| Run | Latency |
|-----|---------|
| 1   | 452ms   |
| 2   | 448ms   |
| 3   | 424ms   |
| 4   | 465ms   |
| 5   | 644ms   |
| **Mean** | **487ms** |
| **Min**  | 424ms   |
| **Max**  | 644ms   |

---

## Content Integrity Verification

The resource metadata reports:
```
checksum: e1dbc03b50bdb995961dc8843df6539b79d03bf49787ed6462189ee97d27eaf3
```

SHA-256 of the exact bytes returned by the resolver:
```
$ sha256sum <<< (resolved content bytes)
e1dbc03b50bdb995961dc8843df6539b79d03bf49787ed6462189ee97d27eaf3
```

**Result: Match.** The resolver's `checksum` field is the SHA-256 of the raw content bytes as served. This confirms the content-addressing claim from the guide: consumers can verify resolution integrity without trusting the transport.

---

## Summary

| Test | HTTP | Latency | Notes |
|------|------|---------|-------|
| DID resolution (mainnet) | 200 | 414ms | Baseline; no DLRs present |
| DID + resourceMetadata | 200 | 748ms | 2 resources listed with full metadata |
| Resource dereference (1) | 200 | 1020ms | Content returned; hash verified |
| Resource dereference (2) | 200 | 753ms | String type returns JSON-encoded value |
| Resource metadata only | 200 | 904ms | Full `contentMetadata` with checksum |
| DID resolution (5-run avg) | 200 | 487ms | Stable latency from AWS us-east-1 |

All four hypotheses confirmed:
1. ✅ DID document resolution works with correct W3C DID Resolution structure
2. ✅ `?resourceMetadata=true` surfaces `linkedResourceMetadata` array
3. ✅ `?resourceId=<uuid>` returns resource content
4. ✅ SHA-256 of resolved content matches metadata `checksum` field exactly

---

## Implementation Notes

For the guide's obligation schema use case, the resolution flow performs as described:
- **Baseline resolution latency:** ~420–650ms from AWS to cheqd resolver (Cloudflare-fronted)
- **Resource dereference adds ~300–600ms overhead** over baseline DID resolution
- **Testnet and mainnet use the same resolver endpoint** — no separate URL needed
- The `checksum` field should be validated client-side before trusting resolved constraint content

For agents making real-time trust decisions, this latency profile suggests:
- Cache resolved obligation schemas at credential issuance time (as the guide recommends)
- Do not defer resolution to the task-execution hot path unless latency is acceptable for the use case

---

## Artifacts

- Implementation guide: `drafts/cheqd-dlr-implementation-guide.md`
- Benchmark script: `experiments/dlr_benchmark.sh` (see appendix)

---

## Appendix: Benchmark Script

```bash
RESOLVER="https://resolver.cheqd.net/1.0/identifiers"
TEST_DID="did:cheqd:testnet:c1685ca0-1f5b-439c-8eb8-5c0e85ab7cd0"
RESOURCE_ID="9ba3922e-d5f5-4f53-b265-fc0d4e988c77"

# Resolve with resource metadata
curl -sL "$RESOLVER/$TEST_DID?resourceMetadata=true"

# Dereference specific resource
curl -sL "$RESOLVER/$TEST_DID?resourceId=$RESOURCE_ID"

# Verify content integrity
CONTENT=$(curl -sL "$RESOLVER/$TEST_DID?resourceId=$RESOURCE_ID")
echo -n "$CONTENT" | sha256sum
# Compare with checksum from metadata
```
