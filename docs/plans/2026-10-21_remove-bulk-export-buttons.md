# 批量清除 Phase P65–P98 噪音导出按钮 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清除 2026-10-20～10-21 两天内 34 个 PR（#2103–#2185，Phase P65→P98）批量注入的约 355 个噪音「复制 MD/JSON」按钮，保留所有功能性复制按钮。

**Architecture:** 机械式批量删除。先用 Node.js codemod 脚本 (`scripts/codemod/remove-bulk-export-buttons.mjs`) 处理纯样板文件；再手工处理「混合按钮」文件（同一文件里既有要删的也有要留的）。按目录分 8 个 commit 推进，每批跑 vitest 验证。

**Tech Stack:** React + TypeScript + vitest + Node.js + git

**Spec:** 本次会话（2026-10-21）brainstorming 输出的「批量清除噪音导出按钮」方案——用户决策：删干净 + 保留 4 类 C 组（复制审计摘要 / 复制源码 / 复制对话 MD-JSON / 复制快照）。

## Global Constraints

- **保留功能性复制按钮**：文案含 `复制路径` / `复制 SHA` / `复制分支` / `复制配置路径` / `复制快照` / `复制审计摘要` / `复制源码` / `复制对话 MD` / `复制对话 JSON` 的按钮 **一律保留**，包括其 state 和 handler。
- **保留通用工具函数**：`src/shared/lib/utils.ts` 的 `copyToClipboard` 不动。
- **每批 commit 必须让 vitest 全绿**：删除完一个目录组后立即 `npx vitest run`，失败先修测试再 commit。
- **不动 docs 历史文档**：`docs/mcp-sage-project-management-organization-plan-20261010.md` 等 Phase 文档是历史记录，不删不改。
- **commit message 格式**：`refactor(ui): remove bulk MD/JSON export buttons (<directory>)`，每批一个 commit。
- **删除后 `grep -c copied` 必须为 0**（B+C 组 state 除外），否则 block 提交。

---

## 删除 / 保留 判定表

| 组 | 文案样例 | 处理 |
|---|---|---|
| **A** | 复制 MD / 复制 JSON / 复制详情 MD / 复制蓝图 / 复制支柱 / 复制管线 / 复制阶段 / 复制规范包 / 复制台账 / 复制清单 / 复制语境 / 复制统计 JSON / 复制全形态 JSON / 复制检查 JSON / 复制检测 JSON / 复制来源 JSON / 复制进度 JSON / 复制任务 MD/JSON / 复制护栏支柱 / 复制全部依据 / 复制置信度 / 复制预设包 | **删**（含 state / handler / JSX / 测试断言） |
| **B** | 复制路径 / 复制 SHA / 复制分支 / 复制配置路径 / 复制快照 | **留** |
| **C** | 复制审计摘要 / 复制源码 / 复制对话 MD / 复制对话 JSON | **留**（用户明示保留） |

---

## 参考样板（清理前实测）

**样板 1 — 纯删除（`src/widgets/todo/TodoItem.tsx`）：**

```tsx
// 删 14-15 行
const [copiedMd, setCopiedMd] = useState(false);
const [copiedJson, setCopiedJson] = useState(false);

// 删 23-38 行（两个 handler）
const handleCopyMd = () => { ... };
const handleCopyJson = () => { ... };

// 删 69-84 行（两个 <button>）
<button data-testid={`todo-item-copy-md-${todo.id}`} ...>{copiedMd ? '已复制MD' : '复制MD'}</button>
<button data-testid={`todo-item-copy-json-${todo.id}`} ...>{copiedJson ? '已复制JSON' : '复制JSON'}</button>
```

清理后该文件从 95 行降到 ~58 行，`useState` import 仍被保留（需确认无其他 state 使用则一并删除）。

**样板 2 — 混合（`src/widgets/settings/ProjectHooksPanel.tsx`，必须手工处理）：**

| 行号 | 内容 | 处理 |
|---|---|---|
| 20 | `const [copiedPath, setCopiedPath] = useState(false);` | 留 |
| 21 | `const [copiedMd, setCopiedMd] = useState(false);` | 留（服务 C 组「复制审计摘要」） |
| 22 | `const [copiedJson, setCopiedJson] = useState(false);` | **删** |
| 23 | `const [copiedConfigPath, setCopiedConfigPath] = useState(false);` | 留 |
| 112–127 | `handleCopyAuditMd` | 留 |
| 129–151 | `handleCopyAuditJson` | **删** |
| 153–162 | `handleCopyPath` | 留 |
| 164–176 | `handleCopyConfigPath` | 留 |
| 203–212 / 290–299 | `data-testid="project-hooks-copy-md-btn"` | 留 |
| 213–221 / 300–308 | `data-testid="project-hooks-copy-json-btn"` | **删** |
| 222–231 / 309–318 | `data-testid="project-hooks-copy-path-btn"` | 留 |
| 232–240 / 319–327 | `data-testid="project-hooks-copy-config-path-btn"` | 留 |

> ⚠️ 注意：该文件里 `copiedMd` 的文案是「已复制摘要 / 复制审计摘要」，**不在** A 组删除正则内（因为含「摘要」）。codemod 天然会正确保留——但 Task 5 必须显式验证这一点。

---

## File Structure

| 目录 | 文件数 | 批次 |
|---|---:|---:|
| `src/widgets/chat/` | 21 | Task 1 |
| `src/widgets/wiki/` | 19 | Task 2 |
| `src/features/project-type/` | 16 | Task 3 |
| `src/pages/` + `src/pages/settings/` | 18 | Task 4 |
| `src/widgets/settings/` | 8 | Task 5 |
| `src/widgets/skills/` + `src/widgets/agents/` | 7 | Task 6 |
| `src/widgets/memory/` + `session/` + `orchestration/` + `todo/` | 10 | Task 7 |
| `src/widgets/welcome/` + `system/` + `src/features/{chat,diagnostic,journal,office,onboarding,scheduled,task-brief,theme,workspace}/` | 17 | Task 8 |

**新增：** `scripts/codemod/remove-bulk-export-buttons.mjs`

---

## Task 0: 建立 codemod 脚本

**Files:**
- Create: `scripts/codemod/remove-bulk-export-buttons.mjs`

**Interfaces:**
- Consumes: CLI 参数 = 待处理 `.tsx` 文件路径列表
- Produces: 就地改写文件；stdout 输出每文件的 `✓ changed` / `- no change` 汇总

- [x] **Step 0.1: 创建目录**

```bash
mkdir -p scripts/codemod && pwd && git rev-parse --abbrev-ref HEAD
```

预期输出：cwd 是 `/home/fz/project/sage/.worktrees/refactor-remove-bulk-export-buttons`，分支是 `refactor/remove-bulk-export-buttons`。

- [x] **Step 0.2: 写脚本**

创建 `scripts/codemod/remove-bulk-export-buttons.mjs`：

```javascript
#!/usr/bin/env node
// Usage: node scripts/codemod/remove-bulk-export-buttons.mjs <file...>
//
// 删除 2026-10-20~10-21 (Phase P65-P98) 批量注入的「复制MD/JSON」噪音按钮样板。
//
// 策略：按「JSX 按钮块 → useState → handler」的顺序删除，每步都以整块为单位，
// 避免留下半个函数导致语法错误。B+C 组（路径/SHA/分支/配置路径/快照/审计摘要/
// 源码/对话MD-JSON）通过 KEEP_RE 白名单保护。

import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// A 组：需要删除的文案
const DELETE_RE = new RegExp(
  [
    '复制\\s?MD',
    '复制\\s?JSON',
    '已复制MD',
    '已复制JSON',
    '已复制支柱',
    '已复制蓝图',
    '已复制管线',
    '已复制阶段',
    '已复制规范包',
    '已复制台账',
    '已复制清单',
    '已复制语境',
    '已复制全部详情',
    '已复制详情\\s?MD',
    '已复制详情\\s?JSON',
    '已复制统计\\s?JSON',
    '已复制全形态',
    '已复制项目\\s?MD',
    '已复制项目\\s?JSON',
    '已复制蓝图\\s?JSON',
    '已复制检查JSON',
    '已复制检测JSON',
    '已复制推荐里程碑',
    '已复制阶段管线',
    '已复制任务MD',
    '已复制任务JSON',
    '已复制来源JSON',
    '已复制进度JSON',
    '已复制护栏支柱',
    '已复制全部依据',
    '已复制置信度',
    '已复制预设包',
  ].join('|'),
);

// B+C 组：这些行必须保留（白名单优先）
const KEEP_RE = new RegExp(
  [
    '复制路径',
    '已复制路径',
    '复制SHA',
    '复制分支',
    '复制配置路径',
    '已复制配置路径',
    '复制快照',
    '已复制快照',
    '复制审计摘要',
    '已复制摘要',
    '复制源码',
    '已复制源码',
    '复制对话MD',
    '复制对话JSON',
    '已复制对话MD',
    '已复制对话JSON',
  ].join('|'),
);

const isDelete = (line) => DELETE_RE.test(line) && !KEEP_RE.test(line);

/** 从第 idx 行向上找到 <button 或 <span 的开标签行，返回该行索引 */
function findJsxStart(lines, idx) {
  for (let i = idx; i >= 0; i--) {
    const m = lines[i].match(/<(button|span|div|a)\b/);
    if (m) return { line: i, tag: m[1] };
  }
  return null;
}

/** 从 start 行向下找到该标签闭合，返回闭合后的行索引（含） */
function findJsxEnd(lines, start, tag) {
  const closeRe = new RegExp(`</${tag}>`);
  // 找第一个开标签闭合位置
  for (let i = start + 1; i < lines.length; i++) {
    if (closeRe.test(lines[i])) return i;
  }
  return lines.length - 1;
}

/** 删除所有含 A 组文案的 <button>/<span>/<a> JSX 块 */
function deleteJsxBlocks(source) {
  const lines = source.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    if (isDelete(lines[i])) {
      const start = findJsxStart(lines, i);
      if (start) {
        // 丢弃 out 中该块已写入的部分
        while (out.length > start.line) out.pop();
        const end = findJsxEnd(lines, start.line, start.tag);
        i = end + 1;
        continue;
      }
    }
    out.push(lines[i]);
    i++;
  }
  return out.join('\n');
}

/** 删除引用已删 state 的 handler：形如 const handleCopyXxx = ... => { ... }; */
function deleteHandlers(source) {
  const lines = source.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const m = lines[i].match(/^\s*const\s+(handleCopy\w+)\s*=/);
    if (m) {
      const name = m[1];
      // 收集整个 handler 块（含续行到顶层 `};`）
      const block = [lines[i]];
      let j = i + 1;
      let depth = (lines[i].match(/[{(]/g) || []).length - (lines[i].match(/[})]/g) || []).length;
      while (j < lines.length && depth > 0) {
        block.push(lines[j]);
        depth += (lines[j].match(/[{(]/g) || []).length - (lines[j].match(/[})]/g) || []).length;
        j++;
      }
      const text = block.join('\n');
      // handler 名里含 A 组语义（Md/Json/Markdown/Blueprint/Pillars...）且不含 B+C 语义
      const isA =
        /(Md|Json|Markdown|Blueprint|Pillars|Pipeline|Stages|BlueprintJson|AllSuite|Card|Drawer|Board|Row|Sider|Stats|Tasks|Source|Progress|Detection|Signal|Vcs|Positioning|Milestone|Preset|Guard)\w*$/.test(name) &&
        !/(Path|Sha|Branch|Config|Snapshot|AuditSummary|SourceCode|Dialog|Conversation)/.test(name);
      if (isA) {
        i = j;
        continue;
      }
      void text;
    }
    out.push(lines[i]);
    i++;
  }
  return out.join('\n');
}

/** 删除不再被引用的 copied* useState 行 */
function deleteStates(source) {
  return source
    .split('\n')
    .filter((line) => {
      const m = line.match(/const\s+\[copied(\w+),\s*setCopied\w+\]\s*=\s*useState/);
      if (!m) return true;
      const name = `copied${m[1]}`;
      // B+C 组保留
      if (/^(copiedPath|copiedConfigPath|copiedSnapshot|copiedSha|copiedBranch|copiedAudit|copiedSourceCode|copiedDialog)/.test(name))
        return true;
      // 若该 state 在本 handler/JSX 之外仍被引用（如 title 提示），保留
      // 简化判定：名字里含 A 组语义则删
      return !/(Md|Json|Markdown|Blueprint|Pillars|Pipeline|Stages|Card|Drawer|Board|Row|Sider|Stats|Tasks|Progress|Detection|Signal|Vcs|Positioning|Milestone|Preset|Guard|SelectorPath|Subtemplates|Dirs|Suite|Stats|Version|ItemId|FileJson)/.test(name);
    })
    .join('\n');
}

/** 清理未使用的 useState import + 连续空行 */
function cleanup(source) {
  let out = source.replace(/\n{3,}/g, '\n\n');
  if (!/\buseState\b/.test(out)) {
    out = out.replace(/import\s*\{\s*useState\s*\}\s*from\s*'react';\n?/g, '');
    out = out.replace(/useState,\s*/g, '');
    out = out.replace(/,\s*useState\s*/g, '');
  }
  return out;
}

function processFile(filePath) {
  const abs = resolve(filePath);
  const source = readFileSync(abs, 'utf8');
  let out = source;
  out = deleteJsxBlocks(out);
  out = deleteHandlers(out);
  out = deleteStates(out);
  out = cleanup(out);
  if (out !== source) {
    writeFileSync(abs, out);
    return true;
  }
  return false;
}

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error('Usage: node scripts/codemod/remove-bulk-export-buttons.mjs <file...>');
  process.exit(1);
}

let changed = 0;
for (const f of files) {
  if (processFile(f)) {
    console.log(`✓ ${f}`);
    changed++;
  } else {
    console.log(`- ${f} (no change)`);
  }
}
console.log(`\nProcessed ${files.length} files, changed ${changed}`);
```

- [x] **Step 0.3: 在样本文件上验证**

```bash
cp src/widgets/todo/TodoItem.tsx /tmp/TodoItem.bak.tsx
node scripts/codemod/remove-bulk-export-buttons.mjs src/widgets/todo/TodoItem.tsx
diff -u /tmp/TodoItem.bak.tsx src/widgets/todo/TodoItem.tsx
```

预期 diff：
- 删 `const [copiedMd, setCopiedMd] = useState(false);`
- 删 `const [copiedJson, setCopiedJson] = useState(false);`
- 删 `handleCopyMd` 块、`handleCopyJson` 块
- 删两个 `<button data-testid="todo-item-copy-*">` 块
- **保留** `useTodoStore` / `complete` / `remove` / `Delete` 按钮 / `priority` span

验证 tsc 通过后还原：

```bash
git checkout src/widgets/todo/TodoItem.tsx && rm /tmp/TodoItem.bak.tsx
```

- [x] **Step 0.4: 提交**

```bash
git add scripts/codemod/remove-bulk-export-buttons.mjs
git commit -m "chore(codemod): add bulk export button cleanup script"
```

---

## Task 1: `src/widgets/chat/` (21 files)

- [x] **Step 1.1: 列出 + 备份**

```bash
cat > /tmp/a-group-re.txt <<'EOF'
复制MD|复制JSON|已复制MD|已复制JSON|已复制支柱|已复制蓝图|已复制管线|已复制阶段|已复制规范包|已复制台账|已复制清单|已复制语境|已复制全部详情|已复制详情MD|已复制详情JSON|已复制统计JSON|已复制全形态|已复制项目MD|已复制项目JSON|已复制蓝图JSON|已复制检查JSON|已复制检测JSON|复制推荐里程碑|复制阶段管线|复制任务MD|复制任务JSON|复制来源JSON|已复制进度JSON|复制护栏支柱|复制全部依据|已复制置信度|已复制预设包
EOF
A_RE=$(cat /tmp/a-group-re.txt)
find src/widgets/chat -name '*.tsx' ! -path '*__tests__*' \
  | xargs grep -lE "$A_RE" > /tmp/batch1.txt
wc -l /tmp/batch1.txt
mkdir -p /tmp/bak/batch1
while IFS= read -r f; do cp "$f" "/tmp/bak/batch1/$(echo "$f" | tr '/' '_')"; done < /tmp/batch1.txt
```

- [x] **Step 1.2: 跑 codemod**

```bash
node scripts/codemod/remove-bulk-export-buttons.mjs $(cat /tmp/batch1.txt)
```

- [x] **Step 1.3: diff 审核（安全网，必做）**

```bash
while IFS= read -r f; do
  echo "=== $f ==="
  diff -u "/tmp/bak/batch1/$(echo "$f" | tr '/' '_')" "$f" | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' | head -20
done < /tmp/batch1.txt | head -300
```

检查点：只有 `copied*` state、`handleCopy*` handler、`复制MD/JSON` 按钮被删；无其他删除。

- [x] **Step 1.4: 残留检查（block gate）**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
KEEP_RE='复制路径|复制SHA|复制分支|复制配置路径|复制快照|复制审计摘要|已复制摘要|复制源码|复制对话MD|复制对话JSON'
while IFS= read -r f; do
  n=$(grep -E "$A_RE" "$f" | grep -vE "$KEEP_RE" | wc -l)
  [ "$n" -gt 0 ] && echo "REMAIN $f: $n"
done < /tmp/batch1.txt
```

预期：无输出。有输出则手工补删后再继续。

- [x] **Step 1.5: tsc + vitest**

```bash
npx tsc --noEmit 2>&1 | head -20
npx vitest run src/widgets/chat 2>&1 | tail -20
```

vitest 失败的典型原因：测试文件里 `getByTestId('*-copy-md')` 找不到元素。逐条删除对应断言 + `fireEvent.click` 步骤，**不删** B+C 组断言。

- [x] **Step 1.6: 提交**

```bash
git add src/widgets/chat
git commit -m "refactor(ui): remove bulk MD/JSON export buttons (widgets/chat)"
```

---

## Task 2: `src/widgets/wiki/` (19 files)

- [x] **Step 2.1: 列出 + 备份 + codemod**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
find src/widgets/wiki -name '*.tsx' ! -path '*__tests__*' | xargs grep -lE "$A_RE" > /tmp/batch2.txt
wc -l /tmp/batch2.txt
mkdir -p /tmp/bak/batch2
while IFS= read -r f; do cp "$f" "/tmp/bak/batch2/$(echo "$f" | tr '/' '_')"; done < /tmp/batch2.txt
node scripts/codemod/remove-bulk-export-buttons.mjs $(cat /tmp/batch2.txt)
```

- [x] **Step 2.2: diff 审核**（同 Task 1.3 格式）

- [x] **Step 2.3: 残留检查**（同 Task 1.4 格式，batch 路径改 batch2）

- [x] **Step 2.4: tsc + vitest**

```bash
npx tsc --noEmit 2>&1 | head -20
npx vitest run src/widgets/wiki 2>&1 | tail -20
```

- [x] **Step 2.5: 提交**

```bash
git add src/widgets/wiki
git commit -m "refactor(ui): remove bulk MD/JSON export buttons (widgets/wiki)"
```

---

## Task 3: `src/features/project-type/` (16 files) — 含重灾区

`src/features/project-type/ProjectTypeSelector.tsx` 单文件含 16 个 `copied*` state，是 codemod 的压力测试。

- [x] **Step 3.1: 列出 + 备份 + codemod**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
find src/features/project-type -name '*.tsx' ! -path '*__tests__*' | xargs grep -lE "$A_RE" > /tmp/batch3.txt
wc -l /tmp/batch3.txt
mkdir -p /tmp/bak/batch3
while IFS= read -r f; do cp "$f" "/tmp/bak/batch3/$(echo "$f" | tr '/' '_')"; done < /tmp/batch3.txt
node scripts/codemod/remove-bulk-export-buttons.mjs $(cat /tmp/batch3.txt)
```

- [x] **Step 3.2: diff 审核**

- [x] **Step 3.3: 重灾区专项检查**

```bash
grep -n "copied" src/features/project-type/ProjectTypeSelector.tsx
```

预期：仅剩 B+C 组（如 `copiedSelectorPath`）；若残留 A 组 state 手工删。

- [x] **Step 3.4: 残留检查**（batch3）

- [x] **Step 3.5: tsc + vitest**

```bash
npx tsc --noEmit 2>&1 | head -20
npx vitest run src/features/project-type 2>&1 | tail -20
```

- [x] **Step 3.6: 提交**

```bash
git add src/features/project-type
git commit -m "refactor(ui): remove bulk MD/JSON export buttons (features/project-type)"
```

---

## Task 4: `src/pages/` + `src/pages/settings/` (18 files)

- [x] **Step 4.1: 列出 + 备份 + codemod**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
find src/pages -name '*.tsx' ! -path '*__tests__*' | xargs grep -lE "$A_RE" > /tmp/batch4.txt
wc -l /tmp/batch4.txt
mkdir -p /tmp/bak/batch4
while IFS= read -r f; do cp "$f" "/tmp/bak/batch4/$(echo "$f" | tr '/' '_')"; done < /tmp/batch4.txt
node scripts/codemod/remove-bulk-export-buttons.mjs $(cat /tmp/batch4.txt)
```

- [x] **Step 4.2: diff 审核**

- [x] **Step 4.3: 残留检查**（batch4）

- [x] **Step 4.4: tsc + vitest**

```bash
npx tsc --noEmit 2>&1 | head -20
npx vitest run src/pages 2>&1 | tail -20
```

- [x] **Step 4.5: 提交**

```bash
git add src/pages
git commit -m "refactor(ui): remove bulk MD/JSON export buttons (pages)"
```

---

## Task 5: `src/widgets/settings/` (8 files) — 含混合文件

**`src/widgets/settings/ProjectHooksPanel.tsx` 必须手工验证**：其 `copiedMd` / 「复制审计摘要」属于 C 组保留，codemod 的 `KEEP_RE` 应正确保护它，但必须人工确认。

- [x] **Step 5.1: 备份 + codemod（排除 ProjectHooksPanel）**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
mkdir -p /tmp/bak/batch5
grep -lE "$A_RE" src/widgets/settings/*.tsx | grep -v __tests__ | grep -v ProjectHooksPanel > /tmp/batch5.txt
cat /tmp/batch5.txt
while IFS= read -r f; do cp "$f" "/tmp/bak/batch5/$(echo "$f" | tr '/' '_')"; done < /tmp/batch5.txt
node scripts/codemod/remove-bulk-export-buttons.mjs $(cat /tmp/batch5.txt)
```

- [x] **Step 5.2: 手工处理 ProjectHooksPanel.tsx**

```bash
cp src/widgets/settings/ProjectHooksPanel.tsx /tmp/bak/batch5/ProjectHooksPanel.tsx
grep -nE 'copied|handleCopy|project-hooks-copy' src/widgets/settings/ProjectHooksPanel.tsx
```

按「参考样板 2」的逐行表格处理：删 `copiedJson`（22 行）、`handleCopyAuditJson`（129–151）、两处 `project-hooks-copy-json-btn`（213–221 / 300–308）。其余全留。

- [x] **Step 5.3: 验证保留项仍在**

```bash
grep -cE 'project-hooks-copy-md-btn|project-hooks-copy-path-btn|project-hooks-copy-config-path-btn' src/widgets/settings/ProjectHooksPanel.tsx
# 预期：4（两个分支各 2 个... 实际为 6，见下）
```

预期：`copy-md-btn` 出现 2 次、`copy-path-btn` 2 次、`copy-config-path-btn` 2 次，共 6。`copy-json-btn` 应为 0。

- [x] **Step 5.4: tsc + vitest**

```bash
npx tsc --noEmit 2>&1 | head -20
npx vitest run src/widgets/settings 2>&1 | tail -20
```

修 `src/widgets/settings/__tests__/ProjectHooksPanel.test.tsx`：删 `project-hooks-copy-json-btn` 相关用例，保留 `copy-md-btn` / `copy-path-btn` / `copy-config-path-btn` 用例。

- [x] **Step 5.5: 提交**

```bash
git add src/widgets/settings
git commit -m "refactor(ui): remove bulk MD/JSON export buttons (widgets/settings)"
```

---

## Task 6: `src/widgets/skills/` + `src/widgets/agents/` (7 files)

- [x] **Step 6.1: 列出 + 备份 + codemod**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
mkdir -p /tmp/bak/batch6
grep -lE "$A_RE" src/widgets/skills/*.tsx src/widgets/agents/*.tsx | grep -v __tests__ > /tmp/batch6.txt
cat /tmp/batch6.txt
while IFS= read -r f; do cp "$f" "/tmp/bak/batch6/$(echo "$f" | tr '/' '_')"; done < /tmp/batch6.txt
node scripts/codemod/remove-bulk-export-buttons.mjs $(cat /tmp/batch6.txt)
```

- [x] **Step 6.2: diff 审核**

- [x] **Step 6.3: 残留检查**（batch6）

- [x] **Step 6.4: tsc + vitest**

```bash
npx tsc --noEmit 2>&1 | head -20
npx vitest run src/widgets/skills src/widgets/agents 2>&1 | tail -20
```

- [x] **Step 6.5: 提交**

```bash
git add src/widgets/skills src/widgets/agents
git commit -m "refactor(ui): remove bulk MD/JSON export buttons (widgets/skills+agents)"
```

---

## Task 7: `src/widgets/memory/` + `session/` + `orchestration/` + `todo/` (10 files)

- [x] **Step 7.1: 列出 + 备份 + codemod**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
mkdir -p /tmp/bak/batch7
grep -lE "$A_RE" src/widgets/memory/*.tsx src/widgets/session/*.tsx src/widgets/orchestration/*.tsx src/widgets/todo/*.tsx | grep -v __tests__ > /tmp/batch7.txt
cat /tmp/batch7.txt
while IFS= read -r f; do cp "$f" "/tmp/bak/batch7/$(echo "$f" | tr '/' '_')"; done < /tmp/batch7.txt
node scripts/codemod/remove-bulk-export-buttons.mjs $(cat /tmp/batch7.txt)
```

- [x] **Step 7.2: diff 审核**

- [x] **Step 7.3: MemoryBrowser 专项检查**

```bash
grep -c "copied" src/widgets/memory/MemoryBrowser.tsx
# 预期：0
```

- [x] **Step 7.4: 残留检查**（batch7）

- [x] **Step 7.5: tsc + vitest**

```bash
npx tsc --noEmit 2>&1 | head -20
npx vitest run src/widgets/memory src/widgets/session src/widgets/orchestration src/widgets/todo 2>&1 | tail -20
```

- [x] **Step 7.6: 提交**

```bash
git add src/widgets/memory src/widgets/session src/widgets/orchestration src/widgets/todo
git commit -m "refactor(ui): remove bulk MD/JSON export buttons (widgets/memory+session+orchestration+todo)"
```

---

## Task 8: 剩余目录 (17 files)

- [x] **Step 8.1: 列出 + 备份 + codemod**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
mkdir -p /tmp/bak/batch8
for d in src/widgets/welcome src/widgets/system src/features/chat src/features/diagnostic \
         src/features/journal src/features/office src/features/onboarding \
         src/features/scheduled src/features/task-brief src/features/theme src/features/workspace; do
  [ -d "$d" ] && find "$d" -name '*.tsx' ! -path '*__tests__*'
done | xargs grep -lE "$A_RE" > /tmp/batch8.txt
wc -l /tmp/batch8.txt
while IFS= read -r f; do cp "$f" "/tmp/bak/batch8/$(echo "$f" | tr '/' '_')"; done < /tmp/batch8.txt
node scripts/codemod/remove-bulk-export-buttons.mjs $(cat /tmp/batch8.txt)
```

- [x] **Step 8.2: diff 审核**

- [x] **Step 8.3: 残留检查**（batch8）

- [x] **Step 8.4: tsc + vitest**

```bash
npx tsc --noEmit 2>&1 | head -20
npx vitest run src/widgets/welcome src/widgets/system src/features 2>&1 | tail -20
```

- [x] **Step 8.5: 提交**

```bash
git add src/widgets/welcome src/widgets/system src/features
git commit -m "refactor(ui): remove bulk MD/JSON export buttons (misc widgets+features)"
```

---

## Task 9: 全局验证 + PR

- [x] **Step 9.1: 全量 vitest**

```bash
npx vitest run 2>&1 | tail -30
```

预期：全绿。有失败逐个修（几乎都是已删 testid 的残留断言）。

- [x] **Step 9.2: A 组全局残留 = 0**

```bash
A_RE=$(cat /tmp/a-group-re.txt)
KEEP_RE='复制路径|复制SHA|复制分支|复制配置路径|复制快照|复制审计摘要|已复制摘要|复制源码|复制对话MD|复制对话JSON'
grep -rnE "$A_RE" src/ --include=*.tsx | grep -v __tests__ | grep -vE "$KEEP_RE" | wc -l
# 预期：0
```

- [x] **Step 9.3: B+C 组数量未减少**

```bash
grep -rnE '复制路径|复制SHA|复制分支|复制配置路径|复制快照|复制审计摘要|已复制摘要|复制源码|复制对话MD|复制对话JSON' src/ --include=*.tsx | grep -v __tests__ | wc -l
# 预期：与清理前基线一致（清理前基线 ≈ 32）
```

若少于基线 → 从 `/tmp/bak/` 还原对应文件。

- [x] **Step 9.4: tsc + eslint + build**

```bash
npx tsc --noEmit 2>&1 | head -20
npx eslint src/ 2>&1 | tail -20
npm run build 2>&1 | tail -20
```

- [x] **Step 9.5: 标记 plan 完成**

把本文件所有 `- [ ]` 改成 `- [x]`。

- [ ] **Step 9.6: push + 开 PR**

> ⏸️ **待用户授权**：依既定约束「未经明确授权不 push、不创建 PR」，Step 9.6 尚未执行。
> 分支 `refactor/remove-bulk-export-buttons` 已在本地完成 13 个 commit（Task 0 rewrite + 10 个分批 + 白名单恢复 + 测试清理），
> 全量 vitest 1937/1937、tsc + eslint + build 全绿、A 组残留 0、B+C 组 40 ≥ 基线 37。

```bash
git push -u origin refactor/remove-bulk-export-buttons
gh pr create --title "refactor(ui): remove bulk MD/JSON export buttons (Phase P65-P98)" --body "见 docs/plans/2026-10-21_remove-bulk-export-buttons.md"
```

---

## Self-Review

### 1. 决策覆盖

| 用户决策 | 落地位置 |
|---|---|
| 删干净（全删 A 组） | Global Constraints 判定表 + Task 0 codemod 的 `DELETE_RE` |
| 保留 B 组（路径/SHA/分支/配置路径/快照） | `KEEP_RE` 白名单 + Task 9.3 数量校验 |
| 保留 C 组（审计摘要/源码/对话 MD-JSON） | `KEEP_RE` 白名单 + Task 5.3 保留项验证 |
| 保留 `copyToClipboard` | Global Constraints（不在 codemod 作用域内） |
| 分批 commit | Task 1–8，每批一个 commit |

### 2. 已知风险（已内置安全网）

| 风险 | 安全网 |
|---|---|
| codemod JSX 删除误伤 | Task N.3 diff 审核（必做）+ Task N.4 残留检查（block gate） |
| codemod 漏删罕见命名 | Task 3.3 重灾区专项 + Task 9.2 全局残留 = 0 |
| codemod 误删 B+C 组 | `KEEP_RE` 白名单 + Task 5.3 + Task 9.3 数量基线 |
| 测试残留断言 | Task N.5 vitest + Task 9.1 全量 vitest |
| 未使用 import | Task N.5 `tsc --noEmit` |

### 3. 落地验证（实测样板）

`src/widgets/todo/TodoItem.tsx`（95 行）清理后预期 ~58 行，删 4 个代码块。`src/widgets/settings/ProjectHooksPanel.tsx`（343 行）只删 3 个代码块，其余 6 个按钮全留。
