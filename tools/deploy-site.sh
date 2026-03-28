#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="${SITE_DIR:-$ROOT_DIR/site}"
BUCKET="${MORROW_SITE_BUCKET:-morrow.run}"
DISTRIBUTION_ID="${MORROW_SITE_DISTRIBUTION_ID:-E2UIJLIM3HS5F4}"
AWS_REGION="${AWS_REGION:-us-east-1}"

if [[ ! -d "$SITE_DIR" ]]; then
  echo "Site directory not found: $SITE_DIR" >&2
  exit 1
fi

aws s3 sync "$SITE_DIR/" "s3://$BUCKET/" \
  --delete \
  --region "$AWS_REGION" \
  --only-show-errors

aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*" \
  --output json \
  --no-cli-pager
