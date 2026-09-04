#!/usr/bin/env bash
# scripts/worktree.sh — Manage git worktrees for parallel feature development
#
# 让多分支并行开发不再撞工作区：每个 feature 分支一个独立 .worktrees/<name>/
# 目录，独立的 (PYTHON_BACKEND_PORT, VITE_DEV_PORT) 端口分配。
#
# Usage:
#   scripts/worktree.sh new <branch> [--base <base-branch>]
#   scripts/worktree.sh list
#   scripts/worktree.sh ports
#   scripts/worktree.sh remove <branch>
#   scripts/worktree.sh clean
#
# 文档：docs/technical/47-git-worktree-workflow.md

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_BASE="${REPO_ROOT}/.worktrees"

usage() {
  cat <<'EOF'
Usage:
  scripts/worktree.sh new <branch> [--base <base-branch>]
  scripts/worktree.sh list
  scripts/worktree.sh ports
  scripts/worktree.sh remove <branch>
  scripts/worktree.sh clean

Examples:
  # 从当前 HEAD 切新分支并开 worktree
  scripts/worktree.sh new feat/my-feature

  # 显式指定基分支
  scripts/worktree.sh new feat/my-feature --base main

  # 查看所有 worktree 的端口分配
  scripts/worktree.sh ports
EOF
}

# "feat/my-feature" → "feat-my-feature"
safe_dir_name() {
  printf '%s' "$1" | tr '/' '-'
}

# 扫描已有 .worktrees/*/.env.local，分配下一个未占用端口对
# 起始 baseline = 主仓库默认 (8765, 1420)，保证第一个 worktree 拿到 8766/1421
# 输出：$PYTHON_BACKEND_PORT / $VITE_DEV_PORT（全局，供调用方使用）
allocate_ports() {
  # 主目录运行的默认端口（来自 backend/main.py:777 与 vite.config.ts）
  local max_backend=8765 max_frontend=1420 f bp fp
  shopt -s nullglob
  for f in "${WORKTREE_BASE}"/*/.env.local; do
    bp=$(grep -E '^PYTHON_BACKEND_PORT=' "$f" 2>/dev/null | cut -d= -f2 || true)
    fp=$(grep -E '^VITE_DEV_PORT=' "$f" 2>/dev/null | cut -d= -f2 || true)
    [[ -n "$bp" && "$bp" =~ ^[0-9]+$ ]] && (( bp > max_backend )) && max_backend="$bp"
    [[ -n "$fp" && "$fp" =~ ^[0-9]+$ ]] && (( fp > max_frontend )) && max_frontend="$fp"
  done
  # declare -g 显式声明为全局，避免被函数内任意 local 污染
  declare -g PYTHON_BACKEND_PORT=$(( max_backend + 1 ))
  declare -g VITE_DEV_PORT=$(( max_frontend + 1 ))
}

cmd_new() {
  local branch="" base=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --base) base="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *)
        if [[ -z "$branch" ]]; then branch="$1"; shift
        else echo "Unexpected arg: $1" >&2; exit 1
        fi
        ;;
    esac
  done

  if [[ -z "$branch" ]]; then
    echo "❌ Branch name required" >&2
    exit 1
  fi

  # 同分支不能两个 worktree 同时 checkout
  if git worktree list --porcelain | grep -qE "^branch refs/heads/${branch}\$"; then
    echo "❌ Branch '${branch}' is already checked out in another worktree:" >&2
    git worktree list | grep "${branch}" >&2 || true
    exit 1
  fi

  local safe_name dir_name
  safe_name=$(safe_dir_name "$branch")
  dir_name="${WORKTREE_BASE}/${safe_name}"

  if [[ -d "$dir_name" ]]; then
    echo "❌ Worktree directory already exists: ${dir_name}" >&2
    echo "   如要复用：'cd ${dir_name}' 或 'scripts/worktree.sh remove ${branch}' 后重试" >&2
    exit 1
  fi

  mkdir -p "${WORKTREE_BASE}"

  # 分配端口
  allocate_ports

  # 创建 worktree（新分支 vs 复用旧分支）
  if git show-ref --verify --quiet "refs/heads/${branch}"; then
    echo "ℹ️  Branch '${branch}' already exists, attaching (no -b)"
    git worktree add "${dir_name}" "${branch}"
  elif [[ -n "$base" ]]; then
    git worktree add -b "${branch}" "${dir_name}" "${base}"
  else
    git worktree add -b "${branch}" "${dir_name}"
  fi

  # 写入端口环境变量
  cat > "${dir_name}/.env.local" <<ENV
PYTHON_BACKEND_PORT=${PYTHON_BACKEND_PORT}
VITE_DEV_PORT=${VITE_DEV_PORT}
ENV

  echo ""
  echo "✅ Worktree created"
  echo "   path:     ${dir_name}"
  echo "   branch:   ${branch}"
  echo "   backend:  ${PYTHON_BACKEND_PORT}"
  echo "   frontend: ${VITE_DEV_PORT}"
  echo ""
  echo "→ cd ${dir_name}"
  echo "→ set -a && source .env.local && set +a"
  echo "→ npm install   # 首次需要"
  echo "→ npm run dev                                  # vite on :${VITE_DEV_PORT}"
  echo "→ /home/fz/anaconda3/envs/sage-backend/bin/python -m backend.main  # backend on :${PYTHON_BACKEND_PORT}"
}

cmd_list() {
  git worktree list
}

cmd_ports() {
  printf '%-60s %-10s %-10s\n' "PATH" "BACKEND" "FRONTEND"
  printf '%-60s %-10s %-10s\n' "$(printf -- '-%.0s' {1..60})" "----------" "----------"
  for d in "${WORKTREE_BASE}"/*/; do
    [[ -f "${d}.env.local" ]] || continue
    local bp fp
    bp=$(grep -E '^PYTHON_BACKEND_PORT=' "${d}.env.local" | cut -d= -f2)
    fp=$(grep -E '^VITE_DEV_PORT=' "${d}.env.local" | cut -d= -f2)
    printf '%-60s %-10s %-10s\n' "${d}" "${bp}" "${fp}"
  done
  echo ""
  echo "Main checkout defaults: backend=8765 frontend=1420"
}

cmd_remove() {
  local branch="${1:-}"
  if [[ -z "$branch" ]]; then
    echo "❌ Branch name required" >&2
    exit 1
  fi

  local safe_name dir_name
  safe_name=$(safe_dir_name "$branch")
  dir_name="${WORKTREE_BASE}/${safe_name}"

  if [[ ! -d "$dir_name" ]]; then
    echo "❌ No worktree at: ${dir_name}" >&2
    exit 1
  fi

  echo "Removing worktree at ${dir_name}..."
  git worktree remove "${dir_name}" --force

  # 如果分支是 'feat/...' / 'fix/...' 这种临时分支，建议也删掉
  if [[ "$branch" =~ ^(feat|fix|refactor|hotfix)/ ]]; then
    if git show-ref --verify --quiet "refs/heads/${branch}"; then
      echo "Deleting ephemeral branch '${branch}' (skip if has unmerged commits)"
      git branch -D "${branch}" 2>/dev/null || echo "  (kept branch — has unmerged commits; delete manually)"
    fi
  fi
}

cmd_clean() {
  echo "Pruning stale worktree metadata..."
  git worktree prune
  echo "Removing empty directories under ${WORKTREE_BASE}/..."
  for d in "${WORKTREE_BASE}"/*/; do
    [[ -d "$d" ]] || continue
    if [[ -z "$(ls -A "$d")" ]]; then
      rmdir "$d"
      echo "  removed: $d"
    fi
  done
  echo "Done."
}

# Main dispatcher
if [[ $# -eq 0 ]]; then usage; exit 0; fi
cmd="$1"; shift
case "$cmd" in
  new)        cmd_new "$@" ;;
  list|ls)    cmd_list ;;
  ports)      cmd_ports ;;
  remove|rm)  cmd_remove "$@" ;;
  clean)      cmd_clean ;;
  -h|--help|help) usage ;;
  *) echo "❌ Unknown command: $cmd" >&2; usage; exit 1 ;;
esac