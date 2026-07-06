#!/usr/bin/env bash
# 创建临时 git 仓库 + 给定 commits，用于测试 infer_tier.py
# 用法: bash sample_repo.sh "feat: x" "fix: y" "feat(scope): z"
# 输出: 新创建的临时仓库路径

set -e

COMMITS=("$@")

tmpdir=$(mktemp -d)
cd "$tmpdir" || exit 1
git init -q -b main
git config user.email "test@example.com"
git config user.name "Test"

# Initial commit on a previous version
echo "# initial" > README.md
git add README.md
git commit -q -m "chore: initial"
git tag v0.4.0

# Apply each provided commit
for msg in "${COMMITS[@]}"; do
    echo "$msg" >> README.md
    git add README.md
    git commit -q -m "$msg"
done

echo "$tmpdir"