# ArenCard 能力移植（P0-P6）验证记录 · 收口

- 日期：2026-09-22（P6 收口）
- 关联：`docs/mcp-aren-card-port-plan.md`（方案 v2，已随本 PR 归档至 `archive/`）、`docs/mcp-arena-p0-verification.md` ~ `docs/mcp-arena-p5-ui.md`（各阶段交付记录）
- 落库：main #1381（squash，27e97566）；win7 对齐 #1383（cherry-pick + py38 兼容修复，merge 7dd23726）
- P6 验收口径（方案 §8）：`test:pr` 通道与 backend pytest 全绿；本文件记录冒烟数据；spec §1.4/§7.1 修订落地；审计文档增补 ArenCard 源；方案文档归档

## 1. 各阶段真实冒烟数据汇总

| 项 | 数据 | 结果 | 证据 |
|---|---|---|---|
| S0-B：Electron 21（Chromium 106）V3 token 被 create-chat 受理 | 隐藏窗口出票 → create-chat 200 | **通过**（协议抽卡路径成立，R1 备选未启用） | `docs/mcp-arena-p1-protocol.md` §S0-B |
| P1 真实注册冒烟（count=3, concurrency=3） | **3/3 成功，job 总耗时 17s**（04:03:06→04:03:23）；邮箱 4~6s 到达；额度 15000×3 回写；user_id 回写；accounts_total=3；导出格式 `邮箱----密码----额度` | **通过** | `docs/mcp-arena-p1-protocol.md` §真实冒烟 |
| P3 token 窗口 | code + tests + smoke 全绿（反节流开关齐备；隐藏窗口可出票）；UA 归一化 3 例回归 | **通过** | `docs/mcp-arena-p3-token-window.md` |
| P4 真实账号抽卡冒烟（住宅代理未接入） | 真实账号导入 3（P1 导出→临时 db）；真实 V3 mint 就绪（隐藏窗口、干净 UA、exit_ip 上报、首票成功）；抽卡 job 启动 running；窗口存活期间按需出票 **6 次**；系统代理（WinINET 127.0.0.1:7890）检测 PASS | **通过**（限定：无代理换 IP 路径未触发） | `docs/mcp-arena-p4-draw-engine.md` §真实冒烟 |
| P4 全量抽卡 ×10 / 换 IP ×1 / token 拒绝率统计 | **未执行**——真实抽卡上量依赖住宅代理接入（P4 结论：数据中心 IP 触发 429/CF 概率高，方案 §11-R6）；后端引擎、门闸、熔断、换 IP 逻辑已由单测/集成覆盖 | **pending 真实资源** | 本文件 §3 |
| P2 代理子系统 | 单测 + 远端套件 + 真机全链路冒烟全绿（`/proxies/test` 真实出口 IP） | **通过** | `docs/mcp-arena-p2-proxies.md` |
| P5 前端 | vitest 全量 2663 passed（当时触点口径）；typecheck 0；scoped eslint 0 | **通过** | `docs/mcp-arena-p5-ui.md` |

## 2. P6 落库时点全量验证（PR #1381 CI + 本地复核）

- **e2e（`test:pr` 通道等价）**：PR #1381 门禁 `stub-smoke` / `stub-deep` / `live-boot` 全部 pass（Playwright electron-stub/live 分层；不进 electron-live-deep，避免真连 arena，符合方案 §9）
- **backend**：CI `Backend (Python)` job 全绿（ruff 0、import-linter KEPT、pytest 全量 coverage ≥ 80%）；arena 触点 16 文件 **213 passed, 1 skipped**（py3.11）
- **frontend**：CI `Frontend (TypeScript)` job 全绿（lint / typecheck / vitest+coverage / build）；落库前本地全量 **2945 passed / 0 failed / 3 skipped**
- **electron**：`arenaTokenWindow` 12 单测；双平台 Electron build + smoke pass
- **win7 LTS（#1383）**：`Backend (Python 3.8, Win7 LTS)` job 全绿；本地 py38 arena 全量 **213 passed, 1 skipped**（修复 2 处 py38 运行期不兼容：tenminmail 锁构造期绑 loop、zip strict= 形参）；win7 前端全量 2781 passed

## 3. 遗留与后续（非 P6 门禁）

1. **真实抽卡 ×10 / 换 IP ×1 / 拒绝率统计**：需住宅代理资源到位后执行（引擎/门闸/熔断已就绪，UI 已可操作）。
2. **token 窗口 in-app 开关**：需后端 config 写入端点（未在 P1-P4 契约内）；当前启停仍走 `arena_automation.yaml` 的 `token_window.enabled`。
3. **arena UI i18n**：与存量三组件一并做统一迁移（P5 记录的偏离项）。
4. **spec §1.4/§7.1 修订**：随本 PR 落地（见下）。

## 4. Spec 修订落点（方案 §10.6）

- `docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md` §1.4：非目标措辞修订——批量注册限定为「用户在本机 UI 显式发起的 job」（独立 flag、默认关、无后台自动创建）
- 同文件 §7.1：凭据加密主密钥从「派生自 `SAGE_LOCAL_AUTH_TOKEN`」修订为「持久化 master.key（arena_keystore）」——原方案在每次后端重启重新生成 token，会导致已存账号永久不可解密（#1381 修复项）
- 审计增补：`docs/technical/50-arena-source-license-audit.md` 追加 ArenCard 参考源附录（只借鉴逻辑与实测常量，代码从零重写）
