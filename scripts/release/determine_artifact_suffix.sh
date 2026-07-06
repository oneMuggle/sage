#!/usr/bin/env bash
# Determine electron-builder artifactName suffix from GitHub tag.
#
# Usage: GITHUB_REF_NAME=v0.5.0-beta.1 bash determine_artifact_suffix.sh
# Output: writes "value=<suffix>" to stdout (for $GITHUB_OUTPUT in workflow)
#
# Suffix mapping:
#   v0.5.0              → win10
#   v0.5.0-lts          → win7
#   v0.5.0-alpha.N      → alpha
#   v0.5.0-beta.N       → beta
#   v0.5.0-rc.N         → rc
#   v0.5.0-alpha.N-lts  → alpha-lts
#   v0.5.0-beta.N-lts   → beta-lts
#   v0.5.0-rc.N-lts     → rc-lts

set -euo pipefail

ref_name="${GITHUB_REF_NAME:-}"

if [[ -z "$ref_name" ]]; then
    echo "::error::GITHUB_REF_NAME is not set" >&2
    exit 1
fi

# Determine tier (alpha / beta / rc / stable)
tier="stable"
if [[ "$ref_name" == *-alpha* ]]; then
    tier="alpha"
elif [[ "$ref_name" == *-beta* ]]; then
    tier="beta"
elif [[ "$ref_name" == *-rc* ]]; then
    tier="rc"
fi

# Determine LTS suffix
is_lts="false"
if [[ "$ref_name" == *-lts ]]; then
    is_lts="true"
fi

# Combine
if [[ "$tier" == "stable" ]]; then
    if [[ "$is_lts" == "true" ]]; then
        suffix="win7"
    else
        suffix="win10"
    fi
else
    if [[ "$is_lts" == "true" ]]; then
        suffix="${tier}-lts"
    else
        suffix="$tier"
    fi
fi

# Emit GitHub Actions output format
echo "value=$suffix"