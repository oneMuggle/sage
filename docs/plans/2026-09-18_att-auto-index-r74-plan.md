# r74 批次计划：附件上传后自动建立检索索引（opt-in，fire-and-forget）

日期：2026-09-18（分支创建于 main@985ada29，含 r66-67 producer/配置）
文件面：新增 src/shared/api/attachmentAutoIndex.ts + 单测；Chat.tsx
上传循环一行接线。

## 背景

RAG 管道（索引端点 #968、IPC #976、producer 检索 #1069、配置面板
#1079）的最后一处断点：**没有任何调用方发起索引**——上传的附件永远
不进向量库，producer 检索总是空手而归。

## 交付

- `attachmentAutoIndex.ts`：`isAttachmentIndexReady()`（开关开 +
  base_url/model 非空 + dim>0）；`maybeIndexAttachment(mediaId)`
  （fire-and-forget：索引成功 chunks>0 时 toast 提示，失败 toast
  警告——不阻断消息发送，R37 fail-safe 口径）
- `Chat.tsx` 上传循环：上传成功即按需触发索引
- 未启用/配置不全 → 完全不触发（零行为变化）

## 测试
4 例（未启用不触发 / 端点不全不触发 / 就绪发起索引且参数正确 /
失败 toast 警告）+ 既有配置模块 4 例全过；tsc/eslint 全绿。

## Win7 对齐
新功能不回流。
