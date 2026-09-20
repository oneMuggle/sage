# r78 批次计划：聊天文件选择器 accept 过滤——从源头防误选

日期：2026-09-18（分支创建于 main@87d7de3f）

## 背景
r75 打通 pdf/docx 上传后，InputCard 的文件选择器（type="file"）仍无
accept 属性——用户可选任意类型（.exe/.zip…），发送时才收到
「不会被发送」警告，体验差。

## 交付
- useFileUpload.ts 导出 CHAT_DOCUMENT_ACCEPT = '.txt,.md,.pdf,.docx'
  （与 CHAT_DOCUMENT_EXTENSIONS 同口径）
- InputCard 文档文件选择器加 accept 提示（浏览器级过滤，从源头防误选）
- ChatInput「不会发送」警告保留作为拖拽/粘贴路径的兜底

## Win7 对齐
新功能不回流。
