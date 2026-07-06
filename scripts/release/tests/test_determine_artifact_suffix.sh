#!/usr/bin/env bash
# Tests for determine_artifact_suffix.sh
# Usage: bash test_determine_artifact_suffix.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SCRIPT_DIR/../determine_artifact_suffix.sh"

fail_count=0

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  ✅ $name"
    else
        echo "  ❌ $name: expected '$expected', got '$actual'"
        fail_count=$((fail_count + 1))
    fi
}

# Helper: run the script with a given ref name and capture the value=
run_suffix() {
    local ref_name="$1"
    local output
    output=$(GITHUB_REF_NAME="$ref_name" bash "$SCRIPT")
    echo "$output" | grep '^value=' | cut -d= -f2-
}

echo "Testing determine_artifact_suffix.sh..."

# Test stable main
result=$(run_suffix "v0.5.0")
assert_eq "stable main → win10" "win10" "$result"

# Test stable LTS
result=$(run_suffix "v0.5.0-lts")
assert_eq "stable LTS → win7" "win7" "$result"

# Test alpha main
result=$(run_suffix "v0.5.0-alpha.1")
assert_eq "alpha main → alpha" "alpha" "$result"

# Test beta LTS
result=$(run_suffix "v0.5.0-beta.2-lts")
assert_eq "beta LTS → beta-lts" "beta-lts" "$result"

# Test rc LTS
result=$(run_suffix "v0.5.0-rc.1-lts")
assert_eq "rc LTS → rc-lts" "rc-lts" "$result"

if [[ $fail_count -eq 0 ]]; then
    echo ""
    echo "All tests passed."
    exit 0
else
    echo ""
    echo "$fail_count test(s) failed."
    exit 1
fi