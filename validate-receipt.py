#!/usr/bin/env python3
"""
EOV Receipt Schema Validation Harness
=======================================
Validates EOV execution receipt JSON instances against eov-receipt-schema-v1.json.

Usage:
    python3 validate-receipt.py                        # validates the bundled example
    python3 validate-receipt.py path/to/receipt.json   # validates a custom receipt

Requirements:
    pip install jsonschema

Part of: draft-morrow-sogomonian-exec-outcome-attest-00
Schema:  eov-receipt-schema-v1.json
"""

import json
import sys
import os
import hashlib
import base64
from pathlib import Path

try:
    import jsonschema
    from jsonschema import validate, ValidationError, SchemaError
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema")
    sys.exit(1)

SCHEMA_PATH = Path(__file__).parent / "eov-receipt-schema-v1.json"

# Minimal example receipt for self-contained testing.
# In a real deployment, the receipt_signature would be a real Ed25519 signature
# over the canonical serialization of all other fields. Here it is a placeholder
# that satisfies the base64url pattern check.
EXAMPLE_RECEIPT = {
    "schema_version": "eov/v1",
    "invocation_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "invocation_context": {
        "invoking_principal": "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        "delegation_token": "sha256:" + "a" * 64,
        "tool_name": "database_write",
        "inputs_hash": "sha256:" + "b" * 64,
        "invocation_timestamp": "2026-04-05T19:00:00.000Z",
    },
    "outcome_claim": {
        "status": "success",
        "outputs_hash": "sha256:" + "c" * 64,
        "completion_timestamp": "2026-04-05T19:00:00.142Z",
        "outcome_detail": "Record written: table=audit_log, row_id=88421, bytes_written=512",
    },
    "signer_identity": {
        "key_id": "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK#key-1",
        "attestation_ref": "https://rats-registry.example/agent/88b4-attestation-20260405",
    },
    "receipt_signature": base64.urlsafe_b64encode(b"\x00" * 64).decode(),
    "receipt_timestamp": "2026-04-05T19:00:00.200Z",
    "transparency_log_ref": {
        "log_id": "sha256:" + "d" * 64,
        "entry_id": "scitt-20260405-88421",
        "submission_timestamp": "2026-04-05T19:00:01.500Z",
    },
}

# An intentionally invalid receipt to verify the schema correctly rejects bad inputs.
INVALID_RECEIPT_CASES = [
    {
        "name": "missing_invocation_id",
        "receipt": {k: v for k, v in EXAMPLE_RECEIPT.items() if k != "invocation_id"},
        "expect_fail": True,
    },
    {
        "name": "bad_status_value",
        "receipt": {
            **EXAMPLE_RECEIPT,
            "outcome_claim": {**EXAMPLE_RECEIPT["outcome_claim"], "status": "unknown_status"},
        },
        "expect_fail": True,
    },
    {
        "name": "wrong_schema_version",
        "receipt": {**EXAMPLE_RECEIPT, "schema_version": "v2"},
        "expect_fail": True,
    },
    {
        "name": "bad_inputs_hash_format",
        "receipt": {
            **EXAMPLE_RECEIPT,
            "invocation_context": {
                **EXAMPLE_RECEIPT["invocation_context"],
                "inputs_hash": "md5:abc123",
            },
        },
        "expect_fail": True,
    },
]


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def validate_receipt(receipt: dict, schema: dict) -> tuple[bool, str]:
    try:
        validate(instance=receipt, schema=schema)
        return True, "VALID"
    except ValidationError as e:
        return False, f"INVALID: {e.message} (path: {' > '.join(str(p) for p in e.path)})"
    except SchemaError as e:
        return False, f"SCHEMA ERROR: {e.message}"


def run_harness(schema):
    passed = 0
    failed = 0

    print("=" * 60)
    print("EOV Receipt Schema Validation Harness")
    print(f"Schema: {SCHEMA_PATH.name}")
    print("=" * 60)

    # Positive case: bundled example
    ok, msg = validate_receipt(EXAMPLE_RECEIPT, schema)
    if ok:
        print(f"  [PASS] bundled_example_receipt: {msg}")
        passed += 1
    else:
        print(f"  [FAIL] bundled_example_receipt: {msg}")
        failed += 1

    # Negative cases: should all fail validation
    for case in INVALID_RECEIPT_CASES:
        ok, msg = validate_receipt(case["receipt"], schema)
        if case["expect_fail"] and not ok:
            print(f"  [PASS] {case['name']}: correctly rejected — {msg}")
            passed += 1
        elif case["expect_fail"] and ok:
            print(f"  [FAIL] {case['name']}: should have been rejected but passed")
            failed += 1
        else:
            print(f"  [FAIL] {case['name']}: unexpected result — {msg}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


def main():
    schema = load_schema()

    if len(sys.argv) > 1:
        # Validate a user-provided receipt file
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"ERROR: File not found: {path}")
            sys.exit(1)
        with open(path) as f:
            receipt = json.load(f)
        ok, msg = validate_receipt(receipt, schema)
        print(f"{path.name}: {msg}")
        sys.exit(0 if ok else 1)
    else:
        # Run the full harness
        ok = run_harness(schema)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
