# R153：MCP OAuth loopback 回调服务单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；MCP OAuth 切片 3b（RFC 8252 §7
  loopback redirect）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`mcp/oauth_loopback.py`（135 行，127.0.0.1 随机端口一次性回调服务：
/callback 捕获完整重定向 URL、其余路径 404、wait 轮询/超时、close/
context manager）此前零测试。真实回环 HTTP 交互测试（127.0.0.1 随机
端口，无外发流量）。

## 覆盖矩阵（约 11 例）

1. 启动：随机端口 >0、redirect_uri 格式 `http://127.0.0.1:{port}/callback`；
2. GET /callback?code=…&state=… → 200、HTML 含"授权完成"、captured
   为完整 URL（含 query）；3. 非callback 路径 → 404 且不污染 captured；
4. wait 返回捕获 URL；5. 未捕获时 wait 短超时 → TimeoutError；
6. close 后端口不再服务；7. context manager 退出自动 close；
8. 二次使用（重新构造）端口可复用服务。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
