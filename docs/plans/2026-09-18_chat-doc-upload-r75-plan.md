# r75 批次计划：聊天 UI 文档附件支持 pdf/docx——打通 R39/RAG 的 UI 断点

日期：2026-09-18（分支创建于 main@d4c6069d）
文件面：src/pages/Chat.tsx 上传过滤器 + MIME 映射常量。

## 背景

R39（pdf/docx 提取）与 RAG 链路（r57-r74）后端全部就绪，但 Chat.tsx
的上传循环仍沿用 R37 的 txt/md 白名单——pdf/docx 附件从 UI 根本不会
上传，后端整条链路对真实用户是死代码。

## 交付
- 扩展名白名单 txt/md → {txt, md, pdf, docx}（与后端 ALLOWED_* 对齐）
- MIME 映射常量（pdf/docx 上传时带正确 content-type）
- r74 自动索引随之覆盖 pdf/docx（索引端点服务端提取）

## 测试
tsc/eslint 全绿；stream/useChat 39 例全过（既有行为零回归——短文档
注入路径不变）。

## Win7 对齐
新功能不回流。
