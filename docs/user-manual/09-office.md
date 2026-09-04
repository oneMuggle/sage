# 09. Office 文档管理

> **适用版本**: Sage main @ 2026-09-04 PR #412 / #414 / #415 / #416 + Win7 同步 PR #417
> **用户入口**: 桌面端 Office 页面(`/office` 路由)+ Chat 内自动调用

## 9.1 什么是 Office CRUD 闭环

Sage 现在可以用**自然语言**帮你增删改查 Word(`.docx`)、Excel(`.xlsx`)、PowerPoint(`.pptx`)三类文档。

完整流程是:**在 chat 里告诉 Sage 你想做什么** —— 它会自动创建文件、修改内容、归档历史版本,并在工作区里管理这些文档的元数据。误删可以恢复,误改可以撤销,二进制文件不会被文本流破坏。

简单说:**Sage 是你的 Office 文档助手,文档跟对话一起走,不会因为切窗口或重启软件而丢失。**

## 9.2 你能用它做什么

### 9.2.1 创建一份新文档

**场景**: "帮我做一份 2026 Q4 销售报告的 PPT"

Sage 会:
1. 让你选择保存到哪个工作区(绑定的当前工作区,或选一个新目录)
3. 根据你描述的标题和大纲生成 PPT
4. 把文件落盘并在 Office 页面登记
5. 把生成的文档链接附在回复里

你会看到:
- 一个 `.pptx` 文件出现在你选的工作区
- Office 页面里多了一条记录
- Chat 回复末尾有"已生成 X 文档,可在 Office 页面查看"

> **小贴士**: 生成 Excel / Word 同理 —— "做一份 2026 年客户满意度调查表(xlsx)"、"写一份季度总结文档(docx)"。

### 9.2.2 修改现有文档

**场景**: "把这份 docx 的标题改成 '2026 年度战略复盘'"

Sage 会:
1. 自动定位你说的文档(用文件名或 `@文件名` 引用)
2. 在改之前**自动备份当前版本**(用户无需感知)
3. 用 python-docx / openpyxl / python-pptx 改文件
4. 更新 Office 页面里的记录(`status` / `updated_at`)

你可以随时让 Sage 改多次,每次改之前都有 snapshot。

### 9.2.3 归档文档

**场景**: "把这份 xlsx 归档,下季度再用"

归档不是删除 —— 文档文件还在磁盘上,只是从 Office 页面和 Sage 的可见列表里**隐藏**起来。

> **注意**: 当前 Sage 没有"归档"按钮入口 —— 你可以告诉 LLM "归档这份",它会用**恢复**工具找到之前归档的版本。如果你直接说要归档,Sage 会提示你目前没有直接工具入口,但你可以通过"恢复"来达到同样效果(后续版本会补 office_archive 工具)。

实际工作流:
- 你:"把 Q3 报告归档"
- Sage:"我目前没有 office_archive 工具,但你描述的归档语义是『从可见列表里移除』—— 如果你确实想从可见列表里移除,我可以用 office_delete,但这是不可逆的。你确认吗?"

### 9.2.4 恢复归档的文档

**场景**: "恢复我 8 月归档的那个 Q3 报告"

Sage 会:
1. 找到你说文件名对应的归档文档(通过元数据中的 `original_filename`)
2. 把它的 `archived_at` 标记清掉
3. 文档重新出现在 Office 页面和列表里

恢复是**幂等**的:文档已经可见时再调一次不会报错,直接返回"已可见"。

### 9.2.5 不让 Sage 用 write_file 写二进制文件

**场景**: 你让 Sage "帮我生成一张 logo.png",但 Sage 走错了路径用 write_file 写文本

Sage 现在会**主动拒绝**写以下扩展名:

| 类型 | 扩展名 |
|---|---|
| 图片 | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.ico` |
| Office / PDF | `.pdf` `.docx` `.xlsx` `.pptx` `.doc` `.xls` `.ppt` |
| 归档 | `.zip` `.tar` `.gz` `.7z` `.rar` 等 |
| 音视频 | `.mp3` `.mp4` `.mov` `.avi` `.mkv` `.wav` 等 |
| 可执行 | `.exe` `.dll` `.so` `.jar` `.pyc` 等 |

报错信息:`binary_extension_blocked: 目标路径扩展名 '.png' 是已知二进制格式,write_file 仅支持文本/源代码写入;如需生成二进制请用专用工具(office_create / 后续 binary 工具),不要让 LLM 直接写文本到二进制扩展名`

正确做法:用 office_create 工具(Word / Excel / PPT)或专用图片生成工具(后续版本会有)。

### 9.2.6 在 chat 里 `@文件名` 引用文档

**场景**: "@Q4-report.pptx 第二页的标题有问题,改一下"

Sage 会:
1. 在 chat ref 解析阶段用文件名查工作区(不是 UUID)
2. 找到你那份 Q4 报告
3. 读第二页内容
4. 调 office_update 改

之前这个功能在文件名路径下会 404(因为后端只接 UUID),现在支持了。

## 9.3 常见问题 FAQ

### Q1. 文档归档后还能找到吗?

**A**: 文件本身还在磁盘上(在工作区目录里),但 Sage 的列表、Office 页面、chat 引用都看不到它(因为列表过滤 `archived_at IS NULL`)。如果你知道文件名,可以让 Sage "恢复 X" —— Sage 会通过 `original_filename` 找到归档行并恢复。

### Q2. 编辑过的文件会自动备份吗?

**A**: 会。每次 `office_update` 成功之前,Sage 会自动把旧版复制到工作区下的 `.snapshots/` 目录,文件名带时间戳前缀(如 `1725436800123-Q4-report.pptx`)。但**没有自动清理** —— 长期使用后 `.snapshots/` 会累积,需要你手动清理(后续版本会加保留期策略)。

### Q3. chat 里 `@文件名` 怎么用?

**A**: 直接在消息里写 `@文件名.ext`,Sage 会自动查工作区里匹配的文件。例如:
- `@Q4-report.pptx 第二页有问题`
- `@客户名单.xlsx 帮我加一列联系方式`

**注意**: `@文件名` 是**精确匹配**(大小写敏感),不能模糊匹配。如果有同名不同类型的文件,Sage 会提示类型不一致。

### Q4. 为什么 LLM 不让我删/写某些文件?

**A**: 两个独立的限制:

| 行为 | 限制原因 | 解决方案 |
|---|---|---|
| LLM 用 write_file 写 `.png` / `.pdf` / `.docx` 等 | 这些是二进制格式,LLM 用 utf-8 文本写会损坏文件 | 用 office_create 工具(Word/Excel/PPT)或专用图片工具 |
| writer 角色不能调 office_delete | writer 是"整理资料"角色,删除是用户决策 | 让 primary 角色或你自己手动操作 |

### Q5. 文档改坏了能撤销吗?

**A**: 三种撤销路径,按时间从新到旧:

1. **最近一次编辑**: 工作区下的 `.snapshots/<时间戳>-<文件名>` 是最近一次 update 之前的版本,可以从文件系统恢复
2. **office_restore**: 如果文档被归档了,可以让 Sage "恢复 X"
3. **office_delete 是不可逆的** —— 真删除前 Sage 会要求你二次确认

### Q6. 为什么我看不到 `/office` 页面?

**A**: 三个可能原因:

1. **你用的是旧版本**:升级到 PR #417(含)之后的版本
2. **Win7 + alpha.11 及之前**:`/office` 路由缺失,需升级
3. **没在工作区**:Office 页面只在绑定工作区后才有内容;你需要先在 Settings 里绑定一个目录

### Q7. 多个工作区之间能互相引用文档吗?

**A**: 不能。`office_doc_scope` 严格限定在当前绑定的工作区下 —— 即使你 `@文件名`,Sage 也只在当前工作区里找。跨工作区引用需要先切换工作区。

### Q8. 文档元数据(`derived_from`、`original_filename`)是什么意思?

**A**: 两个 Sage 自动维护的字段:

- **`original_filename`**: 你(或上传工具)给文件的原始名(如 `Q4报告.pptx`)。Sage 内部用 UUID 重命名为 `<uuid>.pptx`,但保留原始名便于引用。
- **`derived_from`**: 如果这份文档是从另一份文档派生出来的(例如"基于 Q3 模板生成的 Q4 报告"),`derived_from` 指向源文档的 UUID。Lineage 追溯用。

这两个字段在 re-read(再读一次)时**不会丢失**。

## 9.4 注意事项

### 9.4.1 破坏性操作要二次确认

- **`office_delete` 是真删除**:文件 + 数据库行都移除,**不可逆**。Sage 会在执行前问你"确定吗?"
- **`office_update` 会自动 snapshot** 但**不询问**:Sage 默认信任用户的修改请求,但每次 update 前会自动留一份 `.snapshots/` 备份
- **`office_restore` 是幂等的**:已经可见的文档再调一次不报错,直接返回成功

### 9.4.2 工作区绑定

- Office 文档全部在**当前绑定的工作区**下管理,绑定的目录在 Settings 里改
- 切换工作区后,旧的 chat 里 `@文件名` 会失败(文档在新工作区找不到)
- 跨工作区搬文档需要手动复制文件 + 在新工作区 office_create

### 9.4.3 数据本地化

- 所有文档元数据存在**本机 SQLite**(`office_documents` 表)
- 文档文件存在**工作区磁盘**上(不做云同步)
- 删除 session **不会**自动删除磁盘上的 office 文档

### 9.4.4 LLM 行为不可预测时的兜底

虽然 PR-1..4 做了大量防护,但 LLM 仍然可能在某些 corner case 下走错路径。建议:

- 重要的源文档(.docx / .xlsx / .pptx)放在工作区**外面**,让 LLM 只能读不能改
- 工作区内放 LLM 的草稿和工作产物
- 用 Sage 提供的"复制到工作区"路径做单向同步

## 9.5 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| chat 里 `@文件名` 报 404 | 文件名拼错 / 在归档状态 / 不在当前工作区 | 检查文件名 / "恢复"它 / 切换工作区 |
| office_create 报 `content_shape_invalid` | LLM 传了错误形状的参数(PR-1 已修常见 PPT 形状错误) | 让 LLM 重新尝试,或换个描述方式 |
| write_file 报 `binary_extension_blocked` | 扩展名在二进制黑名单里(见 §9.2.5) | 用 office_create 或专用工具 |
| /office 页面空白 | 没绑定工作区 / 数据库表损坏 | Settings 绑定工作区 / 跑 sage doctor |
| Sage 自动 archive / restore 后 archived_at 没变 | 旧版本(PR-1..4 之前) | 升级 |
| Win7 上找不到 /office 页面 | alpha.11 及之前 | 升级到 PR #417 之后的 win7 版本 |

## 9.6 相关文档

- 技术: [`docs/technical/48-office-crud-completion.md`](../technical/48-office-crud-completion.md) —— 5-PR 系列完整说明
- 技术: [`docs/technical/33-office-m1-m2-completion.md`](../technical/33-office-m1-m2-completion.md) —— M1-M2 前置基础
- 用户: [`01-desktop.md`](./01-desktop.md) —— 安装与启动
- 用户: [`06-diagnostics.md`](./06-diagnostics.md) —— 故障排查与日志
- 用户: [`11-sage-doctor.md`](./11-sage-doctor.md) —— sage doctor 自检
- PR 链接:#405 / #412 / #414 / #415 / #416 / #417