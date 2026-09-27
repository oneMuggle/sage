# R167：诊断包 HTTP 端点单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；M1 诊断包（preview/export）+ Round 9
  搜索引擎健康 + Round 14 浏览器健康
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/diagnostic_routes.py`（220 行，诊断包 preview/export + 搜索引擎
健康自检 + 浏览器老化监控四端点）此前零测试。协作者（LlmTraceRecorder、
export_to_zip_bytes、search engines、browser discovery）全 monkeypatch。

## 覆盖矩阵（约 16 例）

preview：
1. 空 snapshot → count=0、其余字段 None/[]；2. 有记录 → count、
oldest/newest（+00:00 → Z 后缀）、sampleUrls 截前 10 条。

export：
3. StreamingResponse：media_type=application/zip、Content-Disposition
   attachment、body 即 zip 字节；4. include_prompts/include_hostname
   透传 exporter；5. app_version 异常 → "unknown"、config 异常 → ""。

search-engines：
6. 未配置引擎如实上报（configured=False）；7. 已配置引擎 check 结果
映射（ok/latencyMs/detail）；8. 全部四引擎出现在响应。

browser：
9. 未发现浏览器 → browserFound=False + 升级指引 warning；
10. 旧内核（< 120）→ 老化 warning；11. 正常版本无 warning；
12. discovery 抛异常按未找到处理。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
