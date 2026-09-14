# 网页访问能力优化 Round 5：下载断点续传 + 浏览器隐身微化 + B2 勘察结论（2026-09-14）

- **状态**：方案完成，实施中
- **上游文档**：Round 1（#742/#748）、Round 2（#756/#759）、Round 3（#763/#765）、Round 4（#769，main only）
- **范围**：main 与 release/win7 双分支（后端 only）
- **编号约定**：D = 下载续传；B = 浏览器隐身；A = 子代理授权勘察
- **方法**：基于 Round 4 交付后的代码勘察（download_tool / agent_tool / permission_gate，附 `file:line`）

## 0. 结论速览

1. **D1 大文件下载无断点续传**：文献 PDF（几十至几百 MB）在弱网/代理链路上传输中断即全部重来；`http_download` 已流式落盘（天然具备续传位点 = 已写字节数），缺的只是 Range 续传与瞬态错误重试。
2. **B1 浏览器通道的自动化暴露面**：CDP 启动的 Chrome 未加 `--disable-blink-features=AutomationControlled`，页面侧 `navigator.webdriver === true` 直接暴露自动化身份——部分反爬脚本以此一票否决。一行 flag 收窄暴露面（真 Chrome 指纹优势不被一行属性葬送）。
3. **A1 子代理浏览器授权（B2）勘察结论**：审批流是 `ApprovalGate` Future + GUI 应答（permission_gate.py:323-347，超时 default-deny），与调用方是否为子代理无关——**技术上可行**；但落地需要变更"子代理只读白名单"契约（agent_tool.py:89-97 + 151-153 描述 + 权限矩阵交叉验证），立独立轮实施，本轮不混入。

## 1. 差距与证据

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| D1 | 中断即重来：流式写入无 Range 续传、无瞬态错误重试 | download_tool.py:268-360（单次 stream，异常即 unlink 放弃） | **P1** |
| B1 | `navigator.webdriver` 暴露：launch flags 无 AutomationControlled 处理 | browser_cdp.py `_build_launch_command` | **P2** |
| A1 | B2 勘察完成，落地需独立契约轮 | agent_tool.py:89-97、permission_gate.py:323-347 | 记录 |

## 2. 方案设计

### 2.1 D1 断点续传（Range resume + 瞬态重试）

`_stream_to_disk` 外层加续传循环（预算 `_MAX_TRANSFER_ATTEMPTS = 3`）：

- **触发**：仅瞬态网络错误（`httpx.TransportError` 族：连接/读/远端协议错误）且**已写字节 > 0** 时续传；HTTP 状态错误、重定向超限、大小超限等确定性失败不重试（口径不变）。
- **续传请求**：向**最后成功的 hop URL**（重定向解析完成后）附 `Range: bytes=<written>-`；响应须为 `206` 且 `Content-Range: bytes <written>-...` 匹配才允许追加写，否则丢弃续传、整段重来（attempt 预算内）。
- **文件**：续传以追加模式打开同一 target（`_open_exclusive` 仅首建时使用；续传前校验已写字节数与本地文件长度一致）；总失败仍 unlink（不留半截文件污染工作区）。
- **重定向协同**：续传请求直接用最终 hop URL（302 已解析完），逐跳 check_host 语义不变（同一 URL 复验）。
- 结果 content 增 `resumed_bytes`（本次会话续传的字节总数，0 = 未发生续传）。

### 2.2 B1 浏览器隐身微化

`_build_launch_command` 追加 `--disable-blink-features=AutomationControlled`：页面侧 `navigator.webdriver` 不再恒为 true，CDP 通道与 Round 1 持久 profile 组合后可过"仅 webdriver 检测"级别的风控。不改其余指纹（TLS/字型级风控仍需人工通道，口径不变）。

### 2.3 A1 勘察结论（记录，不实施）

- 审批链路：工具执行边界 → `ApprovalGate.request`（Future）→ 前端 GUI 按 `request_id` 应答 → 超时 default-deny。
- 子代理与主代理共用同一执行边界与审批队列；因此给子代理注册 EXTERNAL/EXEC 工具后，审批仍能 surfaced 到 GUI——B2 无审批死锁。
- 落地前提：变更 `SUBAGENT_TOOL_WHITELIST` 只读契约的文案与测试（agent_tool.py:151-153 描述、:89-97 清单、test_agent_tool 对应用例），并为 researcher profile 增配 browser 工具（profiles.py 两分支漂移需手工对位）。**立 Round 6 独立轮**。

## 3. 双分支实施策略

| 文件 | 两分支状态 | 冲突预测 |
| --- | --- | --- |
| backend/tools/download_tool.py | Round 1 cherry 后同源 | 零冲突 |
| backend/tools/browser_cdp.py | 同源 | 零冲突 |
| backend/tests/unit/test_download_tool.py / test_browser_persistence.py | 同源 | 零冲突 |

py3.8 纪律 + 零新依赖不变。

## 4. 实施批次

| 批次 | 内容 | 工作量 |
| --- | --- | --- |
| 批次 1 | D1 断点续传 + 单测 | 1 天 |
| 批次 2 | B1 launch flag + 单测 | 0.25 天 |
| 收尾 | cherry(win7) + 测试 | 0.5 天 |

## 5. 测试与验收

- `test_download_tool.py` 扩展：①首段成功后读错误 → Range 续传 206 拼接完整文件；②续传响应非 206 / Content-Range 不匹配 → 整段重来；③重试预算耗尽 → unlink + 失败；④4xx/5xx 不触发续传重试。
- `test_browser_persistence.py` 扩展：launch 命令含 `--disable-blink-features=AutomationControlled`。
- 验收：模拟中途断流的大文件下载最终完整落盘；`navigator.webdriver` flag 不再注入。

## 6. 安全口径与已知限制

- 续传复用逐跳 `check_host`/`_validate_target_url`（同一 final URL 复验），Range 请求不带 credential（续传场景不含登录态增强——`credential_domain` 请求禁用续传以避免会话过期导致的错误拼接，口径：有凭据的下载失败直接报错重试整段）。
- `--disable-blink-features=AutomationControlled` 只收窄 webdriver 自报属性，不伪造其他指纹；不改变门禁与审批语义。
- 已知限制：服务器不支持 Range（无 `Accept-Ranges`/206）时自动退化为整段重试（受 attempt 预算约束）；attempt 预算 3 次为常量，不做指数退避（下载场景收益低）。
