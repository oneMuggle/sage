# 07. 产物面板 (Artifacts Panel)

> **版本**: Sage main @ PR #266
> **用户入口**: Chat 页面右侧抽屉(RightPanel)→ Artifacts Tab

## 7.1 这是什么

Artifacts Panel 是 Chat 会话页面右侧抽屉里的 **Artifacts Tab**。当你让 Sage 帮你**生成文件**(如代码、文档、图片、CSV 等),所有产物会按 session 自动收集到这里,可以预览、查看、跳转到系统文件管理器定位。

简单说:**它是你这一轮对话里"AI 生成了哪些文件"的清单 + 预览器。**

## 7.2 你能在面板里做什么

### 7.2.1 列出本 session 内的所有产物

- 进入 Chat 页面 → 右缘抽屉 → 切到 **Artifacts** Tab
- 默认按生成时间倒序展示(最新的在上)
- 每行显示:文件名、类型 badge(图 / 代码 / Markdown / CSV / 文本)、大小
- 空状态:面板会显示"暂无产物",**直到本 session 内的工具调用生成了第一个文件,才会出现条目**

### 7.2.2 预览产物内容(支持 6 种类型)

点击任一行 → 抽屉中央弹出预览:

| 类型 | 来源工具 | 预览方式 |
|---|---|---|
| 图片 (`image`) | `write_file` 写 `.png`/`.jpg` 等 | 内联渲染 |
| 代码 (`code`) | `write_file` 写 `.py`/`.ts`/`.js` 等 | 等宽字体高亮 |
| JSON (`json`) | `write_file` 写 `.json` | 格式化展示 |
| CSV (`csv`) | `write_file` 写 `.csv` | 表格预览 |
| Markdown (`markdown`) | `write_file` 写 `.md` | 渲染后展示 |
| 文本 (`text`) | `write_file` 写 `.txt`/`.log` 等 | 等宽字体 |

> PDF / Excel 当前不在预览支持范围,会触发下载或外部打开。

### 7.2.3 在系统文件管理器中定位

预览页面右上角有 **"在文件管理器中显示"** 按钮,点击后会调起:

- Windows:资源管理器高亮该文件
- macOS:Finder 定位该文件
- Linux:Nautilus / Dolphin 等依赖桌面环境

如果你的 Sage 是 Win7 / 离线环境,可能调不起系统管理器,这是正常现象。

## 7.3 与 Chat 主区的关系

Artifacts **不会**自动出现在 Chat 消息流里。它只在右侧 Tab 显示,避免主对话区被大量产物文本淹没。两种同时存在:

- **Chat 主区**:显示文字回复与简短的工具调用状态
- **Artifacts Tab**:产物清单 + 预览

如需在主区看某条产物,点 Artifacts 里的 **"跳转到对应消息"**(本期不在范围内)。

## 7.4 已知边界

| 你想做的 | 当前是否支持 |
|---|---|
| 看本 session 产物列表 | ✅ |
| 预览图片/代码/JSON/CSV/Markdown/文本 | ✅ |
| 调起系统文件管理器定位 | ✅(依赖桌面环境) |
| 跨 session 合并查看产物 | ❌(后续) |
| 在产物内搜索 | ❌(后续) |
| 预览 PDF | ❌(后续) |
| 预览 Excel | ❌(后续) |
| 删除产物 | ❌(直接删除磁盘文件即可,面板下次刷新会移除) |
| 导出产物清单 | ❌(后续) |

## 7.5 隐私与数据

- 所有产物数据**仅存储在本机 SQLite**(`artifacts` 表),不上传、不联网
- 删除一个 session 会**级联删除**该 session 下的所有 artifact 记录
- 物理文件的删除**不会**自动同步到 artifacts 表(下次会话刷新时仍可能显示已不存在的条目);遇到这种情况,直接删除产物文件即可
- 任何写入侧异常都不影响 `write_file` 主流程——Artifacts Panel 是**旁路副作用**,即使 DB 临时不可用,文件写入本身仍然成功

## 7.6 故障排查

| 现象 | 处理 |
|---|---|
| Artifacts Tab 为空 | 当前 session 没有写文件类调用;跑一个会写文件的请求试试 |
| 点击预览显示"加载失败" | 后端 fetch 失败,检查 `~/.config/sage/logs/sage-YYYY-MM-DD.ndjson` 找错误;一般是 sqlite 临时锁 |
| "在文件管理器中显示" 没反应 | 桌面环境不支持(Electron shell.openPath);直接复制路径到地址栏 |
| 看到已删除文件的条目 | 下次刷新会消失,也可手动忽略 |
| PDF / Excel 预览不出来 | 暂未支持,按"下载/外部打开"处理 |
