# R154：LLM 调用追踪 ring buffer 单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；DSH-R8 B3 LLM 流录制/回放的追踪组件
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`services/llm_trace/recorder.py`（108 行，进程级 ring buffer + 全局
facade：FIFO 淘汰、snapshot 拷贝、写入前 URL/header 脱敏）此前零测试。

## 覆盖矩阵（约 15 例）

1. TraceRecord frozen 不可变；2. _Recorder append/count/snapshot 顺序
保持；3. maxlen FIFO 淘汰最旧；4. snapshot 返回副本（改列表不影响
内部）；5. clear；6. facade append 走脱敏（redact_url 应用于
upstream_url、redact_headers 应用于请求与响应头）；7. facade
snapshot/count/clear 委托；8. 脱敏导入失败不炸（惰性 import 在
append 时解析）。

redactor 的 redact_url/redact_headers patch 在 redactor 模块命名空间
（append 内惰性 import 从源模块取名）。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
