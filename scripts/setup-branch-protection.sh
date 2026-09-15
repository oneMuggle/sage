#!/usr/bin/env bash
# Setup GitHub branch protection rules for oneMuggle/sage.
#
# Applies the branch-protection table from
#   docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md §3.5
#
# This script handles the FUTURE PATTERN branches via rulesets API:
#   - release/v*       (stabilization branch, created per RC cycle)
#   - release/stable*   (downstream mirror, created by release workflow)
#
# main + release/win7 are protected via the legacy /branches/{}/protection
# API. Apply those before this script if not already done. No-op here.
#
# Usage:
#   bash scripts/setup-branch-protection.sh            # Dry-run (print only)
#   bash scripts/setup-branch-protection.sh --apply    # Apply
#
# Requires: gh CLI authenticated with admin:repo scope on oneMuggle/sage.
#
# Schema reference: GitHub OpenAPI spec at
#   raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json

set -euo pipefail

REPO="oneMuggle/sage"
APPLY_MODE=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY_MODE=1
fi

RULE_NAME_PREFIX="sage"
# GitHub user IDs of accounts allowed to bypass rules on release/stable*
# (currently just the PAT-owning user). Re-fetched on every run so the user
# ID is correctly resolved if it ever changes.
BOT_USERNAME="oneMuggle"

# ──────────────────── helpers ────────────────────

list_rulesets() {
  gh api "repos/${REPO}/rulesets" \
    --jq '.[] | select(.name | startswith("'"${RULE_NAME_PREFIX}"'-")) | {id: .id, name: .name}'
}

delete_existing_rulesets() {
  echo "→ Scanning existing '${RULE_NAME_PREFIX}-*' rulesets..."
  local existing
  existing="$(list_rulesets)"
  if [[ -z "${existing}" ]]; then
    echo "  (none to delete)"
    return 0
  fi
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    local id name
    id="$(echo "${line}" | jq -r '.id')"
    name="$(echo "${line}" | jq -r '.name')"
    if [[ "${APPLY_MODE}" -eq 1 ]]; then
      echo "  DELETE ${id} ${name}"
      gh api -X DELETE "repos/${REPO}/rulesets/${id}" >/dev/null
    else
      echo "  [DRY] DELETE ${id} ${name}"
    fi
  done <<< "${existing}"
}

create_ruleset() {
  local name="$1"
  local body="$2"
  if [[ "${APPLY_MODE}" -eq 1 ]]; then
    echo "→ POST rulesets ${name}"
    gh api -X POST "repos/${REPO}/rulesets" \
      -H 'Accept: application/vnd.github+json' \
      -H 'X-GitHub-Api-Version: 2022-11-28' \
      --input - <<EOF >/dev/null
${body}
EOF
  else
    echo "  [DRY] POST rulesets ${name}"
  fi
}

# ──────────────────── definitions ────────────────────

# Per OpenAPI: rule types use the rule's `title` as the `type` enum value.
# So `pull_request` (NOT `required_pull_request`), `required_status_checks`, etc.
#
# Required parameters:
#   pull_request: dismiss_stale_reviews_on_push, require_code_owner_review,
#                require_last_push_approval, required_approving_review_count,
#                required_review_thread_resolution  (all 5 REQUIRED)
#   required_status_checks: required_status_checks + strict_...
# All other rule types here accept NO parameters field.

# release/v* — stabilization branch during RC. CI is allowed to fast-fail.
# Label check (`fix:` / `hotfix:`) is enforced separately via
# .github/workflows/pr-label-check.yml — see spec §3.4.
RELEASE_V_RULESET='{
  "name": "sage-release-v-pattern",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["refs/heads/release/v*"], "exclude": [] }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    { "type": "pull_request", "parameters": {
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_approving_review_count": 1,
      "required_review_thread_resolution": false
    } }
  ]
}'

# release/stable* — downstream mirror. PAT-only push by the bot account.
# OpenAPI has no `restrictions` rule type, so we use a different pattern:
#   - require PR for everyone
#   - bypass_actors allowlist the bot account, so its PR (or direct push via
#     its fine-grained PAT) can land without review
# Anyone not on the bypass list gets the full pull_request enforcement.
get_bot_user_id() {
  gh api "users/${BOT_USERNAME}" --jq '.id'
}

RELEASE_STABLE_RULESET='{
  "name": "sage-release-stable-pattern",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["refs/heads/release/stable*"], "exclude": [] }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    { "type": "pull_request", "parameters": {
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_approving_review_count": 1,
      "required_review_thread_resolution": false
    } }
  ],
  "bypass_actors": [
    { "actor_id": __BOT_USER_ID__, "actor_type": "User", "bypass_mode": "always" }
  ]
}'

main() {
  echo "Branch protection setup for ${REPO}"
  if [[ "${APPLY_MODE}" -eq 0 ]]; then
    echo "(DRY-RUN — pass --apply to execute)"
  fi
  echo

  local bot_id
  bot_id="$(get_bot_user_id)"
  echo "Bypass actor (${BOT_USERNAME}): id=${bot_id}"

  delete_existing_rulesets
  echo

  # Substitute __BOT_USER_ID__ placeholder in the stable ruleset body
  local stable_body="${RELEASE_STABLE_RULESET//__BOT_USER_ID__/${bot_id}}"

  create_ruleset "sage-release-v-pattern" "${RELEASE_V_RULESET}"
  create_ruleset "sage-release-stable-pattern" "${stable_body}"

  echo
  echo "Done. Verify with:"
  echo "  gh api repos/${REPO}/rulesets \\"
  echo "    | jq '.[] | select(.name | startswith(\"sage-\")) | {name, enforcement, conditions: .conditions.ref_name.include, rules_count: (.rules | length), bypass_actors}'"
  echo
  echo "Verify existing-branch protections (legacy API):"
  echo "  gh api /repos/${REPO}/branches/main/protection | jq '{enforce_admins: .enforce_admins.enabled, reviews: .required_pull_request_reviews.required_approving_review_count, checks: [.required_status_checks.contexts[]]}'"
  echo "  gh api /repos/${REPO}/branches/release%2Fwin7/protection | jq 'same'"
}

main "$@"
