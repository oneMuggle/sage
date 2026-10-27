# `src/` 收敛第 6 批：依赖面 + i18n 并集（2026-10-27）

> 前序：`mcp-win7-converge-src-types-adr`（#2579）、`…-batch2-chat-chain`（#2580）、
> `…-batch3-settings`（#2581）、`…-batch4-5`（#2584 / #2586）。
> 本文对应第 4–5 批盘点里的 §3.2（新依赖）与 §3.5（i18n 并集）。

## 1. 基线

| 分支 | commit |
|---|---|
| `release/win7` | `c145be12`（含 #2574） |
| `main` | `4219d862` |

## 2. `ShikiCodeBlock.tsx`：取 main

main 把整包 `import('shiki')` 换成「core + 逐项动态导入」：

```ts
const highlighterPromise = Promise.all([
  import('shiki/core'),
  import('shiki/engine/javascript'),
]).then(([{ createHighlighterCore }, { createJavaScriptRegexEngine }]) =>
  createHighlighterCore({
    engine: createJavaScriptRegexEngine({ forgiving: true }),
    themes: [import('@shikijs/themes/github-dark'), import('@shikijs/themes/github-light')],
    langs: [import('@shikijs/langs/javascript'), import('@shikijs/langs/typescript'), ...],
  }),
);
```

差别在于**主题与语言变成逐项 chunk**，不再随主包一次性进入首屏 chunk。
win7 侧该文件的 31 行差异全是这段旧实现，无平台分支，故整份取 main。

工作量：254 → 269 行。

## 3. 依赖声明：lock 已是现成的

`package.json` 补两条直接依赖：

| 包 | 版本 |
|---|---|
| `@shikijs/langs` | `4.3.0` |
| `@shikijs/themes` | `4.3.0` |

关键点：这两个包**此前已作为 `shiki@4.3.0` 的传递依赖存在于 `package-lock.json`**
（`packages["node_modules/@shikijs/langs"].version === "4.3.0"`，`shiki` 的 `dependencies` 里也直接列着它们）。
因此只需在 lock 的 root `packages[""].dependencies` 补两行，**lock 实体零改动**：

```
 package-lock.json | 2 +
 package.json      | 2 +
```

这避免了重算 1287 个包的 lock（main 与 win7 的 lock 之间本来有 28134 行差异，重算会引入大量无关噪声）。

> 未做的：main 的 `package.json` 还有 `dompurify` 3.2.4→3.4.15、`eventsource`→`formdata-node`、
> 删除 `rollup-plugin-visualizer`/`vite-node`、新增 `overrides` 块等差异。这些**不属于**本批
> （不为 ShikiCodeBlock 服务），留作独立的「依赖升级批」，以免一次性把 lock 面打开。

## 4. i18n：并集合并

### 4.1 先看全局键集（三文件 × 两语言一起算）

| 指标 | win7 | main | 处理 |
|---|---|---|---|
| 全局键数 | 1216 | 1209 | 并集 = **1221** |
| main 独有 | — | 5 | 补入 |
| win7 独有 | 12 | — | 保留 |
| 键分区不同 | 16（zh）/ 11（en） | | 采用 main 的分区 |
| 同键不同文案 | 47 | | 以 main 为准 |

**main 独有的 5 个键**（RAG 引用与 Office 修复重试）：

`chat.rag_citation`、`chat.rag_citation_chunk`、`chat.rag_citation_source`、
`chat.rag_citations_count`、`chat.rag_citations_toggle`、`office.delivery.repairRetry`。

**win7 独有的 12 个键**（对应 win7 侧仍在的两块能力）：

| 键 | 支撑的组件 |
|---|---|
| `settings.density.label` | `entities/density` 信息密度设置 |
| `settings.network.browser_env{,.hint,.refresh,.recommended,.loading,.error,.fix}` | `features/diagnostic/BrowserEnvironmentSection.tsx` |
| `settings.network.browser_env.status.{pass,warn,fail,na}` | 同上（自检结果徽标） |

**分区差异**（同一键在两个分支放在不同 locale 文件，运行时都合并成一个字典，功能无差别）：

| 键族 | win7 放置 | main 放置 | 采用 |
|---|---|---|---|
| `updates.*`（11 键） | `chatAndSider.ts` | `settingsAndModels.ts` | main |
| `office.preview.*`（4 键） | `settingsAndModels.ts` | `workspaceAndTools.ts` | main |
| `office.generate.*`（3 键，en） | `settingsAndModels.ts` | `workspaceAndTools.ts` | main |

### 4.2 合并算法

1. 以 **main 的 6 个文件为基底**写入工作区；
2. 把 win7 独有的 12 个键按语义锚点插回：
   - `settings.network.browser_env*` → `chatAndSider.ts` 中最后一个 `settings.network.*` 键之后
     （`settings.network.search.engine.zhipu`）；
   - `settings.density.label` → `settingsAndModels.ts` 中 `settings.font.loadError` 之后。

选择「基底 = main」而不是「基底 = win7」的理由：main 的键分区与文案更新，
用 win7 做基底会导致 47 处文案 + 27 处分区反复对不齐。

## 5. 校验

| 检查 | 结果 |
|---|---|
| 键集对称 | zh **1221** = en **1221**，`zh-only` / `en-only` 均为空 |
| 重复键 | 0（插入前后各扫一次） |
| `t('...')` 静态全量扫描 | 623 个源文件、985 个键；缺失 **40** 个 |
| 缺失键归因 | 与收敛前 win7 缺失的 40 个**完全相同**（`chat.find_*`、`chat.memory_*`、`chat.continue_*` 等），属既有缺口，非本批引入 |
| `tsc -p tsconfig.json --noEmit` | 0 error |
| `tsc -p tsconfig.electron.json --noEmit` | 0 error |
| `node scripts/architecture-check.mjs` | rc 0（67 baselined，slack 393） |
| `node scripts/check-font-scale.mjs --max-slack=0` | rc 0（6 baselined，slack 0） |
| `eslint`（改动 ts/tsx，7 个） | 0 error |
| vitest `ShikiCodeBlock.p135` + `shared/lib/i18n` + `shared/lib/__tests__` | 281 passed / 0 failed |

规模：**9 文件，+209 / −182**。

## 6. 剩余（`src/` 收尾）

| 项 | 说明 |
|---|---|
| `pages/Memory.tsx` | win7 独有 350 行（Tabs/Card 结构），需手合并 |
| `widgets/wiki/MarkdownPreview.tsx` | win7 的 KaTeX 插件 |
| `widgets/command/CommandPalette.test.tsx` | win7 独有 132 行 audit 断言 |
| `features/{diagnostic,journal,office}/index.ts` | win7 barrel 额外导出 |
| `pages/{Arena,ArenaAccounts}.tsx` + `widgets/arena/AccountTable.tsx` | 需整域一起裁（单取 main 会让 2 个用例红） |
| `shared/ui/{DropdownMenu,Select,Switch}/index.ts`、`widgets/evolution/index.ts` | main 已删，需先改引用点；`Switch`/`evolution` 无引用可直接删 |
| 行尾归一化 | `WorkspaceBranchPicker.tsx` 等 CRLF → LF，独立 PR |
| 依赖升级 | `dompurify`、`eventsource`→`formdata-node`、`overrides` 块等 |
