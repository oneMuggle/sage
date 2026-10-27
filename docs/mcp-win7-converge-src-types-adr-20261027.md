# `src/shared/api/types*` 结构分歧裁决（2026-10-27）

> 上游：`docs/mcp-win7-converge-backend-b21-23-20261026.md`、`docs/mcp-win7-convergence-plan-20261025.md` §2。
> 本文只裁决 **API 类型层（`src/shared/api/types*`）的物理布局**，并顺带收敛该簇内的内容差异。
> 批次 1（PR #2565）已合并进 `release/win7`；本文对应批次 25。

## 1. 分歧事实

两条分支在 merge-base `476904b4` 之后各自把 `types.ts` 拆开，但拆法不同：

| | main `7412a5c6` | win7 `2aca4832` |
|---|---|---|
| `src/shared/api/types.ts` | **753 行**（barrel + office 契约内联 + 治理函数） | **58 行**（纯 barrel + 治理函数） |
| `types/chatAndEventTypes.ts` | 730 行 | 738 行 |
| `types/domainEntityTypes.ts` | 662 行 | 662 行（与 main 逐字节相同） |
| `types/officeDocTypes.ts` | **不存在** | 714 行 |
| `types/templateAndTaskTypes.ts` | 492 行 | 492 行 |
| `types-multimodal.ts` | 已删除 | 46 行（**零引用**） |
| 导出符号 | 212 | 212 |

真正的分歧只有一处：**office 契约放哪**。main 内联在 `types.ts`，win7 拆成 `types/officeDocTypes.ts`。

## 2. 裁决：保留 win7 的四子模块布局

三条硬约束，任一都足以否决"回归单文件"：

1. **行数上限**：`architecture-policy.json` 的 `global.maxFileLines = 800`，`count-lines` 与 Architecture check 都在 CI 里。
   main 的单文件已 753 行（**94% 预算**），把它和 win7 的 714 行 office 段合并约 **1400 行**，直接越界。
2. **导入方向**：main 的子模块写 `import type { OfficeDocType } from '../types'`（`chatAndEventTypes` / `templateAndTaskTypes` 各一处），
   等于 `types.ts` → 子模块 → `types.ts` 的**类型导入环**；策略里 `forbidCycles: true`。
   win7 的子模块直接 `from './officeDocTypes'`，依赖是 DAG。
3. **合并成本性质**：结构分歧只会让"文件级三方合并"失效，不会让"符号级搬运"失效。
   拆分布局下每个文件都远离 800 行上限，后续新增类型永远有空间。

因此 `types.ts` 顶部已写入固定口径（见该文件第 10–18 行）：与 main 合并时**按符号、不按文件**搬运 ——
main `types.ts` 里的 office 段一律落到 `types/officeDocTypes.ts`，其余段落到同名子模块。

## 3. 顺带收敛的三处内容差异

裁决过程中发现 win7 的差异不只是"布局不同"，还有**契约滞后**（前端类型落后于自己的后端），一并修掉：

### 3.1 office 契约回填 10 处

对照 `backend/office/models.py` 逐一验证：**这些能力 win7 后端全都已实现**，只有前端类型没跟上。

| 类型 | 补的成员 | 后端依据（win7 `backend/office/models.py`） |
|---|---|---|
| `WordMetadataSpec`（新增） | `author/subject/keywords/comments/category` | `WordMetadataSpec` ×7 |
| `WordSectionBreakSpec`（新增） | `start_paragraph` + `page_setup` | ×2 |
| `WordIndexSpec`（新增） | `heading_text` + `placeholder_text` | ×3 |
| `WordPageSetupSpec` | `page_number_format` / `page_number_start`（R53）、`footnote_restart_each_section`（R58） | 均命中 |
| `WordFormatSpec` | `figure_index` / `table_index`（R42）、`section_breaks`（R26/37） | 均命中 |
| `WordTableSpec` | `header_style`（R36） | 命中 |
| `OfficePptReadResult` / `OfficePptGenerateRequest` | `metadata?: WordMetadataSpec`（R52） | 命中 |
| `OfficeWordReadResult` | `footnotes` / `endnotes`（R57/59） | 均命中 |
| `OfficeWordGenerateRequest` | `metadata?: WordMetadataSpec`（R49） | 命中 |

全部为**可选字段**，运行时零影响；只补齐"后端已返回/已接受、前端类型却声明不到"的缺口。

### 3.2 `WorkspaceSearchKind` 补 5 个 `allowed-*` 成员

win7 后端 `backend/api/workspace_routes.py` 早已按 `kind="allowed-" + (doc_type.value if doc_type else "file")` 产出，
前端 `src/features/chat/AtFileMenu.tsx` 的图标表里也写着 `'allowed-file'`，**只有联合类型漏登**。补：
`allowed-file` / `allowed-ppt` / `allowed-word` / `allowed-excel` / `allowed-pdf`。

### 3.3 删除 `src/shared/api/types-multimodal.ts`

- 6 个导出（`MediaKind` / `MediaRef` / `MediaRefMetadata` / `AttachmentUploadResponse` / `TTSToolOutput` / `ImageGenToolOutput`）；
- `git grep types-multimodal -- src electron tests` = **0 命中**，纯死文件；
- main 已删除，且其四个模块里没有任何等价定义（不是搬家，是删功能面）。
保留它只会让每次符号级对比出现 6 个假阳性，故删除。

## 4. 裁决后的状态

| 指标 | 值 |
|---|---|
| 导出符号 | win7 **212** = main **212**，交集 212，双向差 0 |
| 联合类型成员 | 23 个 shared union 全部相等（含 `WorkspaceSearchKind`） |
| 子模块文件 | 5 个，最大 738 行（上限 800） |
| 死文件 | 0 |

## 5. 后续合并操作手册（每批照做）

1. 取 main 与 win7 的 `types*` 全部 blob，各自抽 **导出符号集合** 与 **联合类型成员集合**；
2. 差集里 main 独有的符号 → 按 3.1 的映射落到对应子模块（office 段 → `officeDocTypes.ts`）；
3. main 独有的 **联合成员** → 先查 win7 后端是否已产出该值：已产出则补齐（3.2 型），未产出则记 `intentional` 并写进本文件；
4. win7 独有且零引用的文件 → 与 main 的删除动作对齐；
5. 闸门：`tsc -p tsconfig.json --noEmit`、`tsc -p tsconfig.electron.json --noEmit`、相关 vitest、以及上面的符号/成员对比脚本（宿主侧工具，不入仓）。

## 6. 验证记录

- `tsc -p tsconfig.json --noEmit` → rc 0
- `tsc -p tsconfig.electron.json --noEmit` → rc 0
- 符号与成员对比脚本 → 符号 212/212、union 23/23 全等（基准 main `6885594`）
- 变更文件 `eslint` → 0 error
