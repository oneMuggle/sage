# R125：multimodal 工具封装层单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；r118（multimodal 能力层）/ r120（ASR）
  既有测试
- **范围**：后端 only，三个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/tts_tool.py`（86 行）、`tools/asr_tool.py`（80 行）、
`tools/image_gen_tool.py`（99 行）是模型侧调用多模态能力的工具封装：
未配置模型 → 友好失败；事件循环内/外双通路（线程池 submit asyncio.run
vs 直跑）；异常 → ToolResult(success=False)。能力层已在 r118/r120 覆盖，
本轮钉住封装层的分派与错误契约。

## 覆盖矩阵（约 22 例）

### `backend/tests/unit/tools/test_multimodal_tools.py`

通用（三工具各一）：
1. schema：工具名、required 参数、risk 类、is_blocking；
2. load_config() 为 None → success=False 且错误文案含"未配置"；
3. 无事件循环分支：monkeypatch capability.execute 返回预设结果 →
   ToolResult success、content/output 形态（TTS=api_url、ASR=text、
   ImageGen=refs）；
4. 事件循环内分支（async 用例）：走线程池通路同样成功；
5. execute 抛异常 → success=False、error 前缀（TTS 生成失败 / ASR
   转写失败 / 图像生成失败）；
6. ASR 专属：FileNotFoundError → "音频文件不存在" 文案；
7. ImageGen 专属：参数透传（prompt/size/quality/n）。

monkeypatch 点：`TTSCapability.load_config` / `execute`（类级），避免
真实网络与 settings 依赖。

## 验证

- pytest 新文件 + tools 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 tools/base.py 的注册机制（已有上游用例）；
- 不测 image_gen_tool 的文件落盘细节（MediaStore 已在 r118 覆盖）。
