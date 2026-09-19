# Arena 自动化与模型探针 - 源代码许可证审计

> **审计日期**: 2026-09-16
> **审计人**: Claude (Task 1 of arena-automation-model-probe plan)
> **结论**: ⚠️ **PROCEED WITH CONDITIONS** (两个源项目均无 LICENSE 文件)

---

## 1. 审计摘要

本报告审计两个外部项目的许可证情况,以确认 Sage 项目(license: MIT)能否合法地将其逻辑或代码移植到主分支。

**关键发现**:
- 两个源项目均**无 LICENSE / LICENSE.md / LICENSE.txt 文件**
- 两个源项目均**非 git 仓库**(无法通过 git log 获取作者信息)
- 两个源项目代码文件中**无任何 license header 或 copyright 声明**
- Sage 项目本身采用 **MIT 许可证**(README 第 9 行徽章声明)

---

## 2. 源项目 1: ArenaHelper

### 基本信息

| 项目 | 信息 |
|---|---|
| 路径 | `/home/fz/project/ArenaHelper/` |
| 类型 | C# WinForms/WebView2 桌面应用 |
| 根命名空间 | `ArenaCompanion` |
| 目标框架 | .NET 4.8 |
| git 仓库 | 否 |
| LICENSE 文件 | **不存在** |
| README 文件 | **不存在** |
| COPYING 文件 | **不存在** |

### 许可证查找结果

```
$ ls -la /home/fz/project/ArenaHelper/ | grep -iE 'license|copying|readme'
(空输出 - 无匹配文件)

$ find /home/fz/project/ArenaHelper/ -maxdepth 2 -type f \
    \( -iname "license*" -o -iname "copying*" -o -iname "readme*" \)
(空输出 - 无任何文档文件)

$ grep -r -i "copyright\|license\|gpl\|apache\|mit\|bsd" \
    /home/fz/project/ArenaHelper/ --include="*.cs" \
    --include="*.txt" --include="*.md"
(仅匹配代码标识符如 RateLimit, 无任何 license 文本)
```

### 版权声明

- 源代码文件中无版权声明
- `.csproj` 文件中的 `<RootNamespace>ArenaCompanion</RootNamespace>` 暗示这是个人/小团队项目
- `Properties/AssemblyInfo.cs` 仅声明 `AssemblyVersion("0.0.0.0")`,无 Company / Copyright 字段

### 法定状态

由于**完全缺失 LICENSE 文件**,在法律上该代码默认适用**著作权法保护** —— 即"保留所有权利"(All Rights Reserved)。未经版权所有者明确许可,不得复制、分发、修改或衍生作品。

**这不意味着禁止使用** —— 仅意味着:
- 我们没有从许可证获得的明示许可
- 我们必须**仅借鉴逻辑思想(idea / algorithm)**,不能逐字复制代码(expression)
- 移植时必须从零重写,不能拷贝源文件

---

## 3. 源项目 2: arena-model-probe

### 基本信息

| 项目 | 信息 |
|---|---|
| 路径 | `/home/fz/project/arena-model-probe/` |
| 类型 | Node.js ESM (JavaScript + Python 驱动器) |
| git 仓库 | 否 |
| LICENSE 文件 | **不存在** |
| README 文件 | `README.md`, `README-PYTHON.md` |
| COPYING 文件 | **不存在** |
| package.json | `"private": true` (无 `"license"` 字段) |

### 许可证查找结果

```
$ ls -la /home/fz/project/arena-model-probe/ | grep -iE 'license|copying|readme'
-rw-rw-rw-  1 fz fz 10074  9月 15 13:30 README.md
-rw-rw-rw-  1 fz fz  7694  9月 15 15:43 README-PYTHON.md
(无 LICENSE 文件)

$ grep -r -i "copyright\|license\|gpl\|apache\|mit\|bsd" \
    /home/fz/project/arena-model-probe/ \
    --include="*.py" --include="*.js" --include="*.mjs" \
    --include="*.json" --include="*.md"
(无任何 license 文本, MITM 匹配均为 "Man-In-The-Middle" 技术术语)
```

### package.json 检查

```json
{
  "name": "arena-model-probe",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  ...
}
```

- `"private": true` 表示作者无意将其发布到 npm 公共仓库
- 缺少 `"license"` 字段(标准 npm 元数据应包含此项)

### README.md 内容性质

`README.md` 和 `README-PYTHON.md` 均为纯技术文档(架构说明、使用方法),**不包含许可证声明或版权归属**。

### 法定状态

与 ArenaHelper 相同 —— **默认适用著作权法保护,保留所有权利**。

---

## 4. 兼容性评估

### Sage 项目许可证

Sage 项目采用 **MIT 许可证**(见 `README.md` 第 9 行徽章和第 5 行描述)。

MIT 是**宽松型许可证**,允许:
- 自由使用、修改、分发
- 闭源衍生作品
- 商业用途

**MIT 对外部代码的要求**:
- 必须保留原代码的版权声明和许可证声明
- 不能添加超出 MIT 范围的限制

### 移植场景分析

| 场景 | 是否可行 | 风险 |
|---|---|---|
| **(a) 仅移植逻辑思想** | **可行** | 低 —— 思想不受版权保护(IBM v. Lotus, Google v. Oracle 案例) |
| **(b) 移植逻辑 + 逐字代码** | **需要授权** | 中 —— 即使原代码无 LICENSE,逐字复制仍属侵权 |
| **(c) 移植并修改** | **可行** | 低 —— 修改后的代码是新的衍生作品,但思想必须真正独立实现 |
| **(d) 复制整个文件** | **不可行** | 高 —— 明确侵权,即使改了文件名 |

### 推荐策略

由于两个源项目均无 LICENSE:
1. **Phase 1 (T2-T4)**: 仅借鉴 `src/registry.js`, `src/classify.js`, `src/idmap.js` 的**算法和数据结构设计**,Python 实现必须从零编写,正则表达式和键名表必须重新组织
2. **Phase 2+ (T5-T13)**: 涉及 ArenaHelper 的 C# 代码(WebView2 自动化、auth flow)更敏感 —— 必须**完全重新实现**,不得翻译 C# 到 Python
3. **代码评审**: 每次 PR 必须明确标注"inspiration source: <file>"而非"copy from <file>"

---

## 5. 按文件处置表

以下列出 plan 中后续任务会涉及的所有源文件,以及初步处置判断。

### 来自 arena-model-probe (Node.js)

| 源文件 | 计划移植目标 | 处置 | 说明 |
|---|---|---|---|
| `src/registry.js` | `backend/services/model_probe_py/registry.py` | **needs review** | 无 LICENSE,但仅移植"数据表"(正则、字典),从零重写即可。需 code review 确认未逐字拷贝 |
| `src/classify.js` | `backend/services/model_probe_py/classify.py` | **needs review** | 核心算法(证据融合 + 余弦相似度)。思想可借鉴,代码必须重写 |
| `src/idmap.js` | `backend/services/model_probe_py/idmap.py` | **needs review** | UUID 解析逻辑简单,完全可重写 |
| `src/interceptor.js` | (仅 Node.js worker,不在 Python 端口范围) | **needs review** | Main 分支 T5 计划使用,Win7 不需要。需确认 Node.js worker 桥接合规 |
| `src/learned.js` | 不在 plan 移植范围 | N/A | |
| `src/probe.js` | 不在 plan 移植范围 | N/A | 行为探针逻辑复杂,plan 选择不移植 |
| `src/ui.js` | 不在 plan 移植范围 | N/A | Shadow DOM HUD,Sage 用 React 重写 |
| `src/main.js` | 不在 plan 移植范围 | N/A | 编排逻辑 |
| `tools/build.mjs` | 不在 plan 移植范围 | N/A | Sage 用现有构建系统 |
| `tools/selftest.mjs`, `tools/e2e.mjs`, `tools/verify.mjs` | 思路借鉴,实现从零 | safe | 测试方法论无版权 |
| `tools/cdp-inspect.mjs` | 思路借鉴,实现从零 | safe | CDP 驱动思路公开 |
| `arena_probe.py`, `agent_model_id.py` 等 Python 文件 | 不直接移植,逻辑分散到 Sage 模块 | **needs review** | CDP 客户端代码需从零实现 |
| `dist/arena-model-probe.user.js` | 不移植 | N/A | 油猴脚本 |
| `README.md`, `README-PYTHON.md` | 不移植 | N/A | 文档 |

### 来自 ArenaHelper (C#)

| 源文件 | 计划移植目标 | 处置 | 说明 |
|---|---|---|---|
| `AuthFlow.cs` | T8 ArenaAdapter 借鉴 auth 流程 | **blocked** | C# WebView2 代码必须完全重写为 Python + Playwright/CDP,严禁逐字翻译 |
| `MainForm.cs` (70690 bytes) | T8 ArenaAdapter 借鉴 UI 流程 | **blocked** | WinForms 代码不移植,仅作"流程参考",从零实现 |
| `CandidateCollector.cs` | 不在 plan 移植范围 | N/A | |
| `CandidateStore.cs` | 不在 plan 移植范围 | N/A | |
| `CandidatePage.cs` | 不在 plan 移植范围 | N/A | |
| `ConversationRecovery.cs` | T8 借鉴会话恢复思路 | **needs review** | 思路公开(cookies + localStorage),从零实现 |
| `RetryController.cs` (28637 bytes) | 通用重试逻辑,plan 可能借鉴 | **needs review** | 重试是通用模式,实现独立 |
| `RateLimitTracker.cs`, `RateLimitRecord.cs` | T8 可能借鉴 rate-limit 处理 | **needs review** | HTTP 429 处理是公开规范 |
| `InstanceManager.cs`, `InstanceContext.cs` | 多实例逻辑,不移植 | N/A | |
| `SavedConversation*.cs` | 会话存储,不移植 | N/A | |
| `UiTheme.cs` (21604 bytes) | UI 主题,不移植 | N/A | |
| `*.Designer.cs` | WinForms 设计器代码,不移植 | N/A | |

---

## 6. 条件与障碍

### ⚠️ 条件 (Proceed With Conditions)

1. **禁止逐字复制**: 任何 PR 不得包含从源项目逐字复制的代码块(>10 行连续相同)
2. **从零重写**: 所有 Python 移植必须由 Sage 工程师独立实现,即使参考了源文件的算法
3. **代码注释规范**: 每个移植文件头部必须注明 "Inspired by: arena-model-probe/src/<filename> (algorithm reference, original implementation)" —— 不是"Port of"
4. **Code Review 强化**: T2-T8 的 PR 必须经过 `code-reviewer` agent + 人工双重 review,确认无版权污染
5. **数据表来源声明**: registry.py 中的正则/字典如果参考了源文件,必须在 docstring 中说明"data sources: see registry.md provenance log"

### ❌ 阻塞项

**无** —— 两个源项目均无 LICENSE 但也无明确的"禁止使用"声明。在著作权法默认保护下,借鉴**思想**(idea)而非**表达**(expression)是合法的。

### 🚨 关键风险

- **如果原作者日后添加 LICENSE**(如 GPL 或商业限制),Sage 已发布的代码不受追溯影响(代码已经是独立实现)
- **如果原作者主张侵权**,需要举证"实质性相似" + "接触",Sage 工程师应能证明独立实现过程(git log + commit message + 测试先写)

---

## 7. 审计方法论

### 检查的命令

```bash
# 1. 检查 LICENSE/COPYING/README 文件存在性
ls -la <project>/ | grep -iE 'license|copying|readme'
find <project>/ -maxdepth 2 -type f \
    \( -iname "license*" -o -iname "copying*" -o -iname "readme*" \)

# 2. 检查 package.json / csproj 等元数据
cat arena-model-probe/package.json
cat ArenaHelper/Arena筛选助手.csproj
cat ArenaHelper/Properties/AssemblyInfo.cs

# 3. 搜索源代码中的 license/copyright 文本
grep -r -i "copyright\|license\|gpl\|apache\|mit\|bsd" \
    <project>/ --include="*.cs" --include="*.py" \
    --include="*.js" --include="*.mjs" --include="*.json"

# 4. 检查头部注释
head -20 <source_file>
```

### 检查的文件清单

#### ArenaHelper
- 目录顶层 - 无文档
- Properties/AssemblyInfo.cs - 无 Company/Copyright
- Arena筛选助手.csproj - 无版权字段
- 抽样源代码头部(Program.cs, AccountData.cs, AuthFlow.cs, MainForm.cs) - 无 license header

#### arena-model-probe
- README.md (214 行) - 技术文档,无 license
- README-PYTHON.md (225 行) - 技术文档,无 license
- package.json - `"private": true`,无 `"license"` 字段
- 抽样源代码头部(arena_probe.py, src/registry.js, src/classify.js) - 无 license header

---

## 8. 后续任务指引

基于本审计,Phase 1+ 的任务应:

1. **每个 PR 的 description 包含**:
   ```
   Source inspiration: <file> (idea only, original implementation)
   License status: source has no LICENSE, code independently rewritten
   ```

2. **T2 (registry.py) 提交前检查清单**:
   - [ ] 所有正则表达式从零编写,不复制源文件
   - [ ] 字典数据可参考公开文档整理(MODEL_PATTERNS 来源 = 厂商公开 API 文档)
   - [ ] 文件 docstring 注明"algorithm inspired by arena-model-probe/src/registry.js"

3. **T3-T4 同 T2 规范**

4. **T5-T7 (Node.js worker, 仅 main 分支)**:
   - 即使 Node.js 代码不进入 Win7 分支,版权风险仍存在
   - 建议:Node.js worker 完全从零实现,不参考源文件

5. **T8 (ArenaAdapter)**:
   - ArenaHelper 是 C# WinForms,Sage 用 Python + Playwright/CDP,技术栈不同
   - 重写而非翻译
   - 关键决策(选择器、等待条件、错误恢复)必须独立设计

---

## 9. 结论

**VERDICT: ⚠️ PROCEED WITH CONDITIONS**

**理由**:
- 两个源项目无 LICENSE,但也无明确禁止性声明
- Sage 项目本身是 MIT,允许从无许可证项目借鉴思想
- 关键约束:**严禁逐字复制,所有代码必须从零实现**
- 通过"独立实现 + 算法参考"的方式,可以安全地推进 Phase 1-5 的所有任务

**下一步**:
1. 本报告提交后,在 `docs/technical/50-arena-source-license-audit.md` 归档
2. Task 2 (TDD: registry.py 移植) 可以开始,但必须遵守"从零重写"约束
3. 每个后续 PR 的 code review 必须包含"no verbatim copy from source"检查项

---

**审计结束** - 报告版本 v1.0 - 2026-09-16
