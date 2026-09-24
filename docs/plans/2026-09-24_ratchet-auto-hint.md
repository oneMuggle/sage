# T2：Architecture check 失败时自动评论基线补账提示

日期：2026-09-24
分支：feat/ratchet-auto-hint
状态：实施完成，待 PR

## 背景

行数 ratchet（architecture-baseline.json）要求"谁增长谁补账"，但 feature PR
作者高频遗忘——本轮循环中 #1488（RT26）、#1489（其 win7 同步）连续两个 PR
带红 Architecture check 被合并，导致主干/分支 ratchet 失效，后续无辜 PR
（如 #1483）需要替它们补账才能变绿。

检查脚本失败输出里其实已有正确数字，但深藏在 CI 日志里；把"现成可粘贴"
的 JSON 行直接贴到 PR 评论，把补账成本降到一次复制。

## 内容

1. `scripts/architecture-check.mjs` 新增 `--json` 模式：输出
   `{newViolations, growthViolations}` 机器可读结构，exit 0（执行态语义
   交给调用方）；不带参数的运行保持原有强制退出码不变。
2. `.github/workflows/ci.yml` 的 `architecture-check` job 新增
   `Ratchet bump hint (comment on failure)` step：
   - 触发条件 `failure() && pull_request`（主干 push 失败不评论）；
   - 用 `actions/github-script@v7` 调 `--json`，格式化出可直接粘贴的
     `architecture-baseline.json` 条目（含 POSIX 路径归一）；
   - 评论带 `<!-- ratchet-auto-hint -->` marker，发新提示前先删除同
     marker 的旧评论（同 PR 多次运行去重，不刷屏）。

## 验证

- 干净树：`--json` 输出空 violations；正常模式 exit 0。
- 阳性自检：临时把 `database.py` 基线下调 5 行 → `--json` 准确报出
  `{file, lines: 1844, baselined: 1839, over: 5}`；强制模式 exit 1；
  还原后恢复全绿。
- ci.yml 通过 YAML 解析校验。
