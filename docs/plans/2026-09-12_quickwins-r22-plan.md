# 快赢与缺陷修复批（第二十二轮批次 A）实施计划

> 日期: 2026-09-12 · 分支: `feat/quickwins-r22` · 基于 main @ 5ee3c9d2
> 来源: 第二十一轮差距分析（新 P0 发现：已落地的多模态在生产环境实际
> 不可见 + ASR 通道可被提示注入滥用）。与并发车道零交集。
> Win7 对齐: D1/D8 属**缺陷修复/安全收敛**，修复后视 CI 情况 cherry-pick
> 到 release/win7（多模态 #680 已在 win7 线上）；D7 是可观测性增强，不迁。

## 批次任务

### D1 [P0][S] 媒体渲染 401 —— 多模态结果在生产不可见

- 现状: `MediaAttachment.tsx` 用 `<img src>/<audio src>` 直连
  `http://127.0.0.1:8765/api/v1/media/{id}`；`LocalAuthMiddleware`
  （main.py:718）要求 Bearer 头 → 标签请求 401 → 坏图/无声。
  带 auth 的 `fetchMediaBlobUrl`（IPC relay 注入 token）是零调用死代码。
- 修复: MediaAttachment 挂载时经 `fetchMediaBlobUrl` 取 blob: URL
  （dev 无 bridge 环境回退直连），替换/卸载时 `revokeMediaBlobUrl`。

### D8 [S] ASR 任意文件出网收敛

- 现状: `speech_to_text` 是 `RiskClass.READ`（自动放行），
  `ASRCapability.build_request` 对 `file_path` 全量读字节上传云端
  —— 无扩展名/大小限制，提示注入可零审批把盘上任意文件送出网。
- 修复: build_request 校验音频扩展名白名单
  （mp3/wav/ogg/webm/m4a/flac/aac）+ 25MB 上限（对齐聊天附件），
  inline content 同样限长。拒绝发生在出网之前。

### D7 [P2][S] 启动逐步耗时埋点

- 现状: `[sage-startup]` 只有 4 个时点，db init 与 lifespan-complete
  之间 ~20 步串行初始化是耗时黑盒。
- 修复: `_startup_mark(step)` 埋在 scheduler / review-queue /
  wake-scheduler / telegram-gateway / multi-agent 五个大步之后。

## 测试

- `test_asr_upload_guard` 4 例（扩展名/超限/合法/inline 超限）。
- vitest chat 套件 36 例无回归（MediaAttachment 相关）。
- ruff / tsc 全绿。
