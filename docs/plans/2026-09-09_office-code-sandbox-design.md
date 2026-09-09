# Office 受控代码沙箱（office_script）设计

> **日期**: 2026-09-09  
> **状态**: 设计中（安全评审前置文档，未动工）  
> **作者**: Claude Code  
> **分支**: main（**永不进 release/win7**）  
> **来源**: `docs/plans/2026-09-09_office-competitive-parity-optimization.md` §3.1（收 G12）

---

## 1. 背景与动机

### 1.1 固定工具集的天花板（G12）

Sage 的 Office 能力走「固定工具集」路线：每加一个能力（图表、图片、样式 op、公式……）都要
新增/扩展工具 schema → 参数校验 → prompt 声明 → 前端类型 → 测试，五处同步。对标方案
（`2026-09-09_office-competitive-parity-optimization.md` 差距总览 G12）的结论是：这是
「追赶永远慢一拍」的根因。

### 1.2 主流产品的「模型写代码操作文档库」模式

| 产品 | 模式 | 效果 |
|---|---|---|
| Claude (skills) | 沙箱内让模型直接写 Python，调 python-docx / openpyxl / python-pptx 生成/编辑文档 | 表达力无上限——功能上限只取决于文档库本身 |
| ChatGPT (Code Interpreter) | 沙箱内跑 Python 分析上传的 xlsx（透视/统计/matplotlib 出图），产出真实可下载文件 | 数据分析 + 产物下载闭环 |

两家共同的分水岭：**不让 LLM 走固定操作清单，而是让它直接操作文档库（写代码）**。Sage 已
具备全部底层库（`backend/requirements.txt:58-69`：python-pptx / python-docx / openpyxl /
pandas / PyMuPDF / reportlab），缺的只是「受控地让模型跑一段脚本」这一层。

### 1.3 为什么现在设计

批次 1/2 已补齐图表管线、样式 op、保真读取、office_analyze；剩余长尾需求（奇形怪状的版式、
批量重排、跨表汇总重组……）每个都做成固定工具不经济。需要一个**表达能力通用、边界收得很紧**
的逃生舱口，而不是继续堆工具。

---

## 2. 目标 / 非目标

### 2.1 目标

1. 新增 LLM 工具 `office_script`：在受控沙箱里执行一段**文档域** Python 脚本，可 import
   openpyxl / python-docx / python-pptx / pandas / matplotlib 等白名单库。
2. 沙箱边界：工作区路径白名单、网络全禁、资源上限、每次执行一次用户审批、全程审计。
3. 执行结果回传 stdout（截断）+ 产物清单 + self_check 回读摘要（复用 plan 3.4 已落地的
   `build_self_check`）。
4. 复用既有管线：审批（`permission_gate`）、路径安全（`path_safety.resolve_within`）、
   输出截断与超时（bash 三件套同款语义）。

### 2.2 非目标（明确不做）

- **不做通用 Python 执行**：不装任意 pip 包、不做通用自动化/爬虫/系统管理脚本，只做文档域
  （word/excel/ppt/pdf 读写与衍生图表）。
- **release/win7（Python 3.8）永不启用**：bundled 清单不变，`requirements-bundled.txt` 不进
  任何新依赖；win7 分支的工具注册表直接不包含 `office_script`（不是降级 stub，是彻底剔除）。
- **不追求对抗性隔离**：威胁模型是「防事故 + 防提示注入诱导 + 防数据外传」，不是防御
  恶意 VM 逃逸级攻击者；沙箱内代码与 Sage 同用户权限运行（见 §6 残余风险）。
- 不做脚本的云端执行 / 远程沙箱（数据不出本机是产品卖点，见 §2.2 of 对标方案）。

---

## 3. 姿态选项对比

| 选项 | 机制 | 隔离强度 | 依赖/体积 | 复用度 | 主要风险 |
|---|---|---|---|---|---|
| **A. 受限 exec 沙箱（推荐）** | `subprocess` 启动专用 venv 的 python.exe，cwd=工作区，env 剥除代理，无网 + AST/audit hook 双防线 | 进程级（OS 边界） | 零新增运行时（复用主 venv 的库集）；venv 磁盘占用 ~150MB 可缓存共享 | 高：审批/输出/超时/kill 全套复用 bash 三件套（`bash_tool.py:101,372,421`）模式 | Windows 无真 chroot，进程内路径逃逸需靠 AST+audit hook 补（§4.1） |
| B. 进程内 RestrictedPython | 在 Sage 后端进程内跑受限字节码 | 无进程边界；历史上多次被对象图遍历逃逸 | +1 个库 | 中 | CPU/内存无法限额（共享进程）；脚本崩溃 = 后端崩溃；GIL 下死循环拖垮全服务 |
| C. WASM（pyodide） | 浏览器/Node 内嵌 WASM CPython | 强（沙箱语义清晰） | 运行时 ~10MB+；pandas/matplotlib 的 WASM 版重且慢 | 低：文件桥接、与本地工作区/审批管线全部要新写 | 工程量大、与「本地文档、本地数据」架构错位 |

### 3.1 推荐：A（受限 exec 沙箱）

理由：

1. **边界清晰**：子进程崩溃/超时可被 `kill`（复用 `kill_shell` 语义），资源上限有 OS 级抓手
   （Windows Job Object，见 §8 开放问题 1），不会波及 Sage 主进程——B 选项的致命缺陷。
2. **复用度最高**：`bash` / `bash_output` / `kill_shell` 三件套已经解决了「子进程执行」的
   全部工程问题——超时、输出字节截断、僵尸进程回收、审批接入（`permission_gate`）、
   WRITE_LOCAL 风险分级。office_script 沿同一套管线，边际成本低。
3. **依赖现实**：文档库已是 Sage 主 venv 的现有依赖（pandas/matplotlib 仅 main 通道），
   临时 venv 只是从主 venv「挑选白名单子集」，不需要新 wheel；C 选项则要为 WASM 重新验证
   整个库矩阵。
4. **架构对齐**：Claude skills / Code Interpreter 的公开描述均为「容器/进程沙箱内跑
   Python」，与 A 同构；将来如需更强隔离，A 的接口（`office_script`）不变，可整体替换执行器。

B 不作为唯一边界，但 B 的**静态检查思想**被 A 吸收为第一道防线（§4.6 的 AST 白名单检查）。

---

## 4. 安全边界设计（关键）

> 总原则：**静态 AST 检查（提交前）+ 运行时 audit hook（执行中）+ 环境最小化（venv 白名单 +
> env 剥除）三道防线**；任何一道被绕过，还有审批与审计兜底留痕。

### 4.1 工作区路径白名单（chroot 式）

Windows 无低成本 chroot，用「约定 + 校验 + 审计」逼近：

- 脚本执行时 cwd = 会话工作区（无绑定时拒绝执行，返回 `workspace_binding_required`）；
  环境变量注入 `SAGE_WORKSPACE=<workspace 绝对路径>`，脚本内 IO 统一走注入的
  `sage_office` helper（见下）。
- helper 的所有读写入口先过 `backend/office/path_safety.py:69 resolve_within(workspace, candidate)`
  ——复用现成的 `..`/symlink 逃逸防护，越界抛 `OfficePathError`。
- **静态检查**：脚本源码中出现绝对盘符路径（`r"C:\`、`/home/`）、`..` 段、`Path.home()`、
  `expanduser` 一律拒绝（error: `path_escape suspected`）。
- **运行时兜底**：子进程启动时通过 wrapper 注册 `sys.addaudithook`，对 `open` /
  `os.rename` / `os.remove` / `shutil.*` 等审计事件校验路径落在工作区内，越界立即抛异常并
  终止（事件同时写入审计日志，见 §4.5）。

### 4.2 网络全禁

- **env 剥除**：子进程 env 白名单制——只传 `SYSTEMROOT`/`TEMP`/`PATH`(指向 venv) 等必需项，
  `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY` 及一切 `*_PROXY` 不传入。
- **socket 封禁**：audit hook 对 `socket.connect` / `socket.bind` / `socket.getaddrinfo`
  一律拒绝；AST 检查禁止 `import socket / urllib / http / requests / httpx / ftplib /
  smtplib / asyncio.streams`。
- **依赖不配合**：白名单 venv 不安装任何网络库（无 requests/httpx/urllib3），第三方库想
  联网也没有轮子。
- 残余风险：C 扩展绕过 audit hook 直连 socket——白名单 venv 内的 C 扩展只有
  openpyxl/pandas/matplotlib 等知名库，无可信度问题（§6 残余风险表）。

### 4.3 资源上限

| 维度 | 上限 | 实现抓手 |
|---|---|---|
| 墙钟超时 | 默认 60s（`ToolPolicy.timeout_seconds` 派生，工具参数不可越过） | 复用 bash 管线超时 + 硬 kill |
| CPU / 内存 | 内存默认 1GB、CPU 时间默认 60s | 首选 Windows Job Object（`JOBOBJECTLIMIT_PROCESS_MEMORY` + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`）；备选 psutil 轮询 kill（§8 开放问题 1） |
| stdout/stderr | 各 ≤ `max_output_bytes`（head + truncated 标记，bash 同语义） | 复用 bash 输出收集管线 |
| 产物 | 单文件 ≤ 100MB、产物总数 ≤ 20、总体 ≤ 500MB，超限中止并清理 | wrapper 在 helper 写入口计数 |
| 脚本体积 | 源码 ≤ 32KB | 工具参数校验 |

### 4.4 审批门禁

- `office_script` 声明 `risk = RiskClass.WRITE_LOCAL`（`backend/domain/risk.py:39`），天然进入
  既有审批分类。
- **每次脚本执行一次审批**（不 remember）：复用 `backend/services/permission_gate.py:329
  ApprovalGate.request`；审批卡展示 `purpose`（一句话意图）+ 脚本摘要（行数/导入清单，
  复用 `summarize_tool_args` 模式），脚本全文可展开查看——对抗提示注入诱导的关键透明度
  设计（§6）。
- 首次构建沙箱 venv（或白名单集变化后重建）也是一次独立审批，展示将安装的依赖锁定清单。

### 4.5 审计日志

- 复用 permission gate 的决策记录（`ApprovalGate._record_decision`）登记「谁、哪个会话、
  批准了哪个脚本」。
- 新增 sandbox 审计记录（追加写 JSONL，`logs/` 下）：`script_sha256`、`purpose`、
  `duration_ms`、`exit_code`、产物清单（工作区相对路径 + bytes）、audit hook 拦截事件
  （被拒的 import/路径/网络调用）。脚本**原文不落审计日志**（可能含用户数据，只存 hash +
  审批卡快照），保留期与现有日志一致。

### 4.6 依赖白名单与导入黑名单（静态 + 运行时双防线）

- **白名单 venv**：沙箱专用 venv 只安装（hash 锁定）：
  `openpyxl / python-docx / python-pptx / pandas / matplotlib / numpy（传递依赖）` +
  注入的域内模块 `sage_office`（封装 `backend/office/charts.py`、`word/excel/ppt` 读写
  helper，见 §5）。标准库按**允许子集**放行（`json/re/math/datetime/collections/itertools/
  functools/random/csv/textwrap/uuid/pathlib(受限)/typing` 等）。
- **导入黑名单**（AST 检查，submit 前执行）：
  `subprocess / socket / ctypes / multiprocessing / threading(起进程线程绕审计) /
  importlib / builtins(重绑) / os.system|os.popen|os.exec*|os.spawn* / eval / exec /
  compile / __import__ / open(裸调用)`——脚本一律改用 `sage_office` 的 IO 入口。
- **双防线**：AST 静态检查挡住显式写法；运行时 audit hook 挡住动态构造
  （`eval("__import__('socket')")`、`getattr(os, 'system')`、`exec(compile(...))`）——
  audit hook 对 `exec` / `compile` / `import` 事件按同一黑名单复核。两道防线由不同代码
  路径实现，避免单点绕过。
- 违规不是「运行到一半才炸」：AST 检查在审批前完成，违规直接返回
  `script_rejected: <规则名>`，不进审批、不计数。

---

## 5. 工具接口草案

```
office_script
├─ script:  str   # Python 源码，≤32KB；以 sage_office helper 为主 API
└─ purpose: str   # 一句话意图（审批卡标题；缺省拒绝执行）

→ ToolResult(success, content={
    stdout:        str,            # ≤ max_output_bytes，head+truncated
    exit_code:     int,
    duration_ms:   int,
    artifacts:     [{path, bytes}],# 工作区相对路径，按 mtime 排序
    self_check:    {...},          # 复用 build_self_check 对主产物回读
    error?:        str             # script_rejected / timeout / killed / ...
  })
```

- 注册：`backend/domain/tool_names.py` + `backend/tools/office_script_tool.py` +
  `backend/tools/__init__.py`；`profiles.py` 能力声明同步（prompt-drift 规则，PR checklist 项）。
- `requires_tool_context = True`（必须绑定会话工作区，无绑定 fail-closed）。
- self_check 语义与 office_create / office_update 一致：回读失败不失败主结果
  （`backend/tools/office_create_tool.py build_self_check`）。
- 执行器伪码：

```
1. AST 检查（黑名单 + 路径字面量）         → 违规: script_rejected
2. ApprovalGate.request（WRITE_LOCAL）     → 拒绝: user_denied
3. 确保沙箱 venv 存在（白名单 hash 命中）  → 首次: 触发依赖审批
4. subprocess(venv_python, wrapper, cwd=workspace, env=白名单, job=资源上限)
5. 收 stdout/stderr（cap）→ 超时/超内存 → kill → error
6. 扫描工作区 diff → artifacts 清单 → build_self_check(主产物)
7. 审计日志落盘 → ToolResult
```

---

## 6. 威胁模型（STRIDE 简表）

| 威胁 | 场景 | 缓解 | 残余风险 |
|---|---|---|---|
| **S**poofing | 伪造审批上下文/会话绕过审批 | ApprovalGate 与 session 绑定；审批请求经 IPC 由前端用户作答 | 低（与既有 bash 审批同级） |
| **T**ampering | 脚本改写工作区外用户文件 | §4.1 三层：AST 字面量检查 + helper `resolve_within` + audit hook 拦截 `open/rename/remove` | C 扩展绕过 audit hook 直接调 WinAPI——白名单 venv 内均为知名库，可信度可接受；进一步收口需受限 token（后续项） |
| **R**epudiation | 用户/模型否认执行过某脚本 | §4.5 审计：script hash + 审批决策记录 + 产物清单 | 审计日志本身被脚本删除——日志写在沙箱不可见的用户数据目录 |
| **I**nformation disclosure | 数据外传（把 xlsx 内容发往网络 / 藏进文件名） | §4.2 网络全禁（env 剥除 + socket 封禁 + 无网络库）；产物清单审计可见异常命名 | 隐信道（时序、文件系统编码）理论存在；**提示注入诱导用户批准恶意脚本**是更现实的通道——缓解：审批卡强制展示 purpose + 导入清单 + 脚本全文可展开，且每次执行都要重新批准（不 remember） |
| **D**oS | 死循环 / 内存炸弹 / 生成海量文件 | §4.3 超时硬 kill + Job Object 内存/CPU 上限 + 产物数量/体积 cap | Job Object 覆盖不到的句柄泄漏（子进程孙进程）——`KILL_ON_JOB_CLOSE` + 禁止 `multiprocessing` 双重缓解 |
| **E**levation of Privilege | 任意代码执行本身（沙箱即 CE） | 进程边界 + 白名单 venv（无可提权工具）+ env 最小化（无凭据类变量注入） | 沙箱内代码与 Sage 同用户权限运行，本设计**不**宣称对抗同用户恶意代码——这是 §2.2 声明的非目标 |

---

## 7. 分阶段落地路线与验收标准

### P0 — 原型（约 1 周，配置默认关）

- 沙箱 venv 构建脚本 + wrapper（audit hook + `sage_office` 注入）
- AST 检查器 + 黑名单规则表
- 执行器（subprocess + 超时 + 输出 cap），不经审批，仅内部开关 `office_script.enabled=false`
- **验收**：20 个代表性脚本（跨表汇总、批量改样式、matplotlib 出图插 Word、xlsx→PDF 级联）
  全部跑通；超时/超内存/越界路径/违规 import 四类负路径行为正确；Sage 主进程不受脚本崩溃影响。

### P1 — 审批与审计（约 1 周）

- 接入 `permission_gate`（每次一审批，审批卡 purpose + 导入清单 + 全文可展开）
- 审计日志（JSONL）+ `bash` 同款输出管线对齐
- `office_script` 注册进工具表 + profiles 能力声明
- **验收**：未批准不执行（含 remember=false 验证）；审批拒绝/超时/kill 全部有审计记录；
  单元 + 集成测试覆盖 §4 全部防线（含 audit hook 拦截动态 `eval` 构造的用例）。

### P2 — 依赖白名单固化（3-5 天）

- venv 依赖 hash 锁定 + 构建缓存 + 白名单集变化检测（重建审批）
- 契约测试：`requirements-bundled.txt` 不含沙箱依赖（`test_office_bundled_requirements.py`
  扩展）；win7 构建产物断言无 `office_script`
- **验收**：CI 断言白名单集合精确匹配；越权 import 被 AST 与运行时**各自独立**拦截的
  用例集通过；`PARITY.md` 状态一致。

---

## 8. 开放问题（提交安全评审）

1. **资源限制抓手**：Windows Job Object（精准、需 pywin32 或 ctypes 包装——ctypes 只允许
   出现在 Sage 侧 wrapper，不进脚本）vs psutil 轮询（实现简单、有 kill 延迟窗口）。倾向
   Job Object + psutil 兜底轮询双保险。
2. **py38 分支隔离方式**：release/win7 工具注册表彻底不注册（倾向，符合「彻底剔除」非目标）
   vs 注册但执行即返回 `unsupported_channel`（防御纵深但引入死代码）。请评审定夺。
3. **脚本产物归属与 artifact 注册**：产物是否写入 `office_documents`（成为受管文档，可被
   office_list/office_read 读写）还是仅进 artifacts 面板？多产物时「主产物」（self_check
   对象）如何选择（倾向：`sage_office` 显式 `ctx.set_primary(path)`，缺省取最大新文件）。
4. **venv 安装源**：离线/内网用户首建沙箱 venv 时 pip 不可达——是否随安装器分发预打包
   wheel 缓存（体积 +~150MB 安装包，需过 bundled 清单评审）vs 首用时降级提示。
5. **数据入口形态**：大 xlsx 是传路径（脚本内全量读）还是注入采样到上下文？影响
   `sage_office` API 设计与「数据不出本机」的话术一致性。
6. **审批疲劳**：每次一审批在长任务里可能被用户无条件点确认（提示注入的经济学）。是否
   引入「同会话白名单脚本 hash 复用批准」？倾向 P1 先不做，观察真实使用后再定。

---

## 9. 参考

- 内部：`2026-09-09_office-competitive-parity-optimization.md` §3.1/G12；
  `backend/tools/bash_tool.py`（超时/输出/kill 管线）；`backend/services/permission_gate.py`
  （审批门禁）；`backend/office/path_safety.py:69`（`resolve_within`）；
  `backend/tools/office_create_tool.py`（`build_self_check` 回读）；
  `backend/domain/risk.py:39`（WRITE_LOCAL）。
- 外部：Claude Help Center — Create and edit files with Claude（沙箱内代码操作文档库）；
  OpenAI — ChatGPT Code Interpreter（上传文件分析 + 产物下载）。
