# r79 批次计划：InputCard 文件选择器 accept 属性补回

日期：2026-09-18（分支基于当前 main 最新）

## 背景
r78 批次（#1184）的 squash 合并只带上了计划文档与 useFileUpload.ts
导出——InputCard.tsx 的 accept=".txt,.md,.pdf,.docx" 属性在合并中
丢失，用户在聊天文件选择器中仍可选任意类型。

## 交付
- InputCard 文档文件选择器补 accept=".txt,.md,.pdf,.docx"
  （浏览器级过滤，从源头防止误选不支持的文件类型）

## Win7 对齐
新功能不回流。
