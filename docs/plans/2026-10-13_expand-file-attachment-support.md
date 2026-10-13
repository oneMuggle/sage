# 扩展聊天文件附件支持

> 日期：2026-10-13
> 分支：feat/expand-file-attachments
> 状态：已完成

## 背景

当前拖放文件到聊天输入框时，只有图片可直接发送，文本文档(txt/md/pdf/docx)虽已支持上传但提示文案误导用户以为不支持，其他文件类型(py/js/csv/xlsx等)则完全被拒绝并显示"普通文件附件暂不随消息发送（即将支持）"的提示。

## 目标

1. 扩展支持的文档/代码文件类型（覆盖常见编程语言和办公格式）
2. 修正误导性的提示文案
3. 让拖放体验与「+」菜单文件选择器的 `accept` 一致

## 涉及文件

| 文件 | 改动内容 |
|------|---------|
| `src/shared/lib/hooks/useFileUpload.ts` | 扩展 `CHAT_DOCUMENT_EXTENSIONS` |
| `src/widgets/chat/InputCard.tsx` | 更新 file input `accept` |
| `src/shared/lib/i18n/locales/zh/chatAndSider.ts` | 修正提示文案 |
| `src/shared/lib/i18n/locales/en/chatAndSider.ts` | 同步英文翻译 |
| `src/widgets/chat/ChatInput.tsx` | 调整 toast 文案 |
| `backend/api/chat_attachment_routes.py` | 扩展 `ALLOWED_TEXT_EXTENSIONS` + 新增 xlsx 提取 |
| `backend/services/multimodal/media_store.py` | `load()` 扩展名白名单加入 `.xlsx` |

## 技术方案

### 第一层：扩展文本/代码文件

后端 `ALLOWED_TEXT_EXTENSIONS` 扩展，按 UTF-8 全文读取注入上下文（与 txt/md 同管道）：

```
py, js, ts, jsx, tsx, json, yaml, yml, xml, html, css,
sh, bat, ps1, sql, r, go, rs, java, c, cpp, h, hpp,
log, ini, toml, cfg, conf, env, gitignore, dockerfile,
makefile, cmake, gradle, properties, csv
```

### 第二层：新增 xlsx 提取

复用已有依赖（openpyxl 用于 Office 预览模块）：

| 扩展名 | 提取方式 | 依赖 |
|--------|---------|------|
| xlsx | openpyxl 遍历 sheet → 文本 | 已有 |
| csv | UTF-8 直读（归入文本类） | 无 |

### 第三层：前端 UX 修正

- `CHAT_DOCUMENT_EXTENSIONS` 与后端 `ALLOWED_TEXT_EXTENSIONS + ALLOWED_DOC_EXTENSIONS` 同口径
- `chat.attachment_not_sent` 文案改为精准描述不支持的类型
- file input `accept` 更新

## 实施步骤

- [x] 步骤 1：后端扩展 `ALLOWED_TEXT_EXTENSIONS` + xlsx 提取
- [x] 步骤 2：前端扩展 `CHAT_DOCUMENT_EXTENSIONS` + `accept` 更新
- [x] 步骤 3：修正 i18n 提示文案
- [x] 步骤 4：更新测试（前端 12 passed + 后端 6 passed + media_store 16 passed）
- [ ] 步骤 5：本地验证（待 PR merge 后在桌面端验证）

## 风险评估

- 低：纯扩展白名单 + 文案修改，不改变既有管道
- xlsx 提取依赖 openpyxl（项目 Office 模块已安装）
