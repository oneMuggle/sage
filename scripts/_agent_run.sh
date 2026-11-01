set -o pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" >/dev/null 2>&1 || true
export PATH=/usr/bin:/d/software/Git/Git/cmd:/d/software/Scoop/shims:$PATH; tr -d "\000" < _push.log | grep -E "forced|EXIT|rejected|fatal" | tail -3; gh pr view 792 --json headRefOid,mergeStateStatus --jq "\"792 head=\(.headRefOid[0:8]) \(.mergeStateStatus)\""
