#!/usr/bin/env bash
# Run the scanners plugins.qgis.org runs on the upload zip.
# Bandit and detect-secrets block an upload; flake8 is advisory.
set -uo pipefail
cd "$(dirname "$0")"
zip=$(./build_zip.sh) || exit 1
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
unzip -q "$zip" -d "$dir"
status=0
echo "== bandit (blocking)"
uvx bandit -q -r "$dir" || status=1
echo "== detect-secrets (blocking)"
uvx --from detect-secrets detect-secrets scan --all-files "$dir" \
  | python3 -c 'import json, sys; r = json.load(sys.stdin)["results"]; print(r or "no secrets found"); sys.exit(1 if r else 0)' \
  || status=1
echo "== flake8 (advisory)"
uvx flake8 "$dir" || true
exit $status
