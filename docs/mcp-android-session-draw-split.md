# 会话与抽卡拆分 · Trace Inspector 对照

## 1. 产品拆分

会话页只做一件事：打开某个 Arena 对话。保留返回与标题。标题展示：

- 当前模型名（每轮探针最新值）
- 所属账户邮箱
- 额度（见 §3，不再假装 credits 还活着）

抽卡不出现在会话主界面，也不要从会话「开始」跳进协议抽卡。入口只在会话列表 / 会话页的**菜单「抽卡」**。

抽卡页在开始前必填：

- 参与的账户（多选，显示邮箱）
- 每账户抽卡次数
- 并发数（协议抽卡）
- 账户池抽完后是否注册新号继续
- 保留规则（正则）

跑起来只显示进度日志与取消。WebView 出票藏在后台。

## 2. 协议并发

`drawOnce` 已是纯 HTTP。多账户可并行，上限用信号量（默认 2，最大 8）。

约束：reCAPTCHA WebView 出票必须串行（一把锁）。Cookie / 代理按账户隔离；每个账户自己的 transport，禁止共享登录态。

池内账户各抽完 N 次后，若开启「开新号继续」：协议注册 → 新账户入池 → 再抽 N 次，直到用户取消。

## 3. 对照 arena-trace-inspector 2.3.1

必须改口径，不能继续只打 `/api/billing/balance`：

- 该接口已对任何请求 403 `Route not allowed`。额度应读 `/api/me/pulse`：`pulse` 是**剩余百分比**，不是 credits。
- 美元额度只在 run trace 的 `spend.recorded`（`allowanceUsd` / `balanceRemainingUsd`）。安卓协议抽卡暂时没有完整 span 详情；会话页先显示 pulse%，有快照再补 USD。
- 模型名有三层：Arena 内部名（可带 `-low/-high/-max`）≠ 供应商请求 id ≠ 响应 id。探针 UI 名与内部名可能不同；抽卡结果应尽量保留 `internal`。档位是配置标签，不是推理强度。
- 抽卡每轮最好等模型名稳定再跳下一个会话（inspector 等 span 详情最多 20s）。安卓协议路径至少在 `drawOnce` 返回的 model/internal 落盘后再抽下一发。

本轮先落地：拆分 UI、抽卡池设置、pulse 百分比、会话标题。span/USD 快照下一轮。
