# 故障排除

本文档帮助你诊断和解决 Sage 常见的问题。

## 应用启动问题

### 问题: 应用无法启动

**症状:**
- 点击图标后无反应
- 启动后立即崩溃
- 显示错误对话框

**解决方案:**

1. **检查系统要求**
   - Windows: 需要 Windows 10/11 (64位) 或 Windows 7 SP1 (LTS 版本)
   - macOS: 需要 macOS 10.13+
   - Linux: 需要 glibc 2.31+ (Ubuntu 20.04+, Debian 11+)
   - 内存: 至少 4 GB RAM

2. **查看日志文件**
   - Windows: `%APPDATA%\sage\logs\main.log`
   - macOS: `~/Library/Application Support/sage/logs/main.log`
   - Linux: `~/.config/sage/logs/main.log`

3. **尝试命令行启动**
   ```bash
   # Windows (PowerShell)
   & "C:\Program Files\Sage\Sage.exe" --no-sandbox
   
   # macOS
   /Applications/Sage.app/Contents/MacOS/Sage --no-sandbox
   
   # Linux
   /usr/bin/sage --no-sandbox
   ```

4. **重新安装**
   - 卸载当前版本
   - 删除应用数据目录(保留配置文件)
   - 重新下载安装

### 问题: 启动后显示空白窗口

**症状:**
- 应用启动但窗口为空白
- 无法加载任何内容

**解决方案:**

1. **检查后端服务**
   - 打开开发者工具 (Ctrl+Shift+I)
   - 查看控制台错误信息
   - 检查后端是否正常运行

2. **重启后端**
   - 关闭应用
   2. 删除后端进程锁文件:
      - Windows: `%APPDATA%\sage\backend.pid`
      - macOS/Linux: `~/.config/sage/backend.pid`
   - 重新启动应用

3. **检查端口占用**
   ```bash
   # 查看 8765 端口是否被占用
   netstat -ano | findstr :8765  # Windows
   lsof -i :8765                 # macOS/Linux
   ```

## API 连接问题

### 问题: API 测试连接失败

**症状:**
- 设置页面点击"测试连接"显示失败
- 错误信息: "连接超时" 或 "认证失败"

**解决方案:**

1. **验证 API 端点配置**
   - 检查 Base URL 是否正确(包含 `/v1` 后缀)
   - 检查 API Key 是否正确(无多余空格)
   - 确认 API Key 有足够权限

2. **检查网络连接**
   ```bash
   # 测试 API 端点是否可达
   curl https://api.openai.com/v1/models \
     -H "Authorization: Bearer YOUR_API_KEY"
   ```

3. **检查防火墙/代理**
   - 确认防火墙未阻止应用
   - 如使用代理,在设置中配置代理地址

4. **查看 API 提供商状态**
   - OpenAI: https://status.openai.com
   - Anthropic: https://status.anthropic.com

### 问题: 对话时出现 401 错误

**症状:**
- 对话时显示 "本地授权凭据无效或缺失"
- 或 API 返回 401 Unauthorized

**解决方案:**

1. **检查 Token 一致性**
   - 这是 SKIP_BACKEND 模式的常见问题
   - 确保 Electron 和后端使用相同的 `SAGE_LOCAL_AUTH_TOKEN`

2. **重启应用**
   - 关闭所有 Sage 进程
   - 重新启动应用(正常模式)

3. **查看诊断信息**
   - 打开开发者工具
   - 查看控制台中的 token 信息
   - 比对 Electron 和后端的 token 是否一致

## 记忆系统问题

### 问题: 记忆不保存

**症状:**
- 对话后记忆页面没有新记录
- 重启应用后记忆丢失

**解决方案:**

1. **检查数据库文件**
   - 确认数据库文件存在:
     - Windows: `%APPDATA%\sage\sage.db`
     - macOS: `~/Library/Application Support/sage/sage.db`
     - Linux: `~/.config/sage/sage.db`

2. **检查磁盘空间**
   ```bash
   # 查看数据库文件大小
   ls -lh ~/.config/sage/sage.db  # Linux/macOS
   dir %APPDATA%\sage\sage.db     # Windows
   ```

3. **修复数据库**
   ```bash
   # 备份数据库
   cp sage.db sage.db.backup
   
   # 使用 SQLite 修复
   sqlite3 sage.db "VACUUM;"
   ```

### 问题: 记忆检索缓慢

**症状:**
- 对话时等待时间很长
- 记忆页面加载缓慢

**解决方案:**

1. **修剪旧记忆**
   - 打开设置 → 记忆
   - 点击"修剪记忆"
   - 保留最近 1000 条记忆

2. **优化数据库**
   ```bash
   sqlite3 sage.db "ANALYZE;"
   sqlite3 sage.db "VACUUM;"
   ```

3. **检查向量数据库**
   - 如果使用 ChromaDB,检查其状态
   - 考虑重建向量索引

## Office 功能问题

### 问题: 无法生成 Word 文档

**症状:**
- 点击生成后无反应
- 或生成失败显示错误

**解决方案:**

1. **检查 Python 后端**
   - 确认后端正在运行
   - 查看后端日志:
     ```bash
     # Linux/macOS
     tail -f ~/.config/sage/logs/backend.log
     
     # Windows
     Get-Content %APPDATA%\sage\logs\backend.log -Wait
     ```

2. **检查依赖**
   ```bash
   # 进入后端环境
   conda activate sage-backend
   
   # 检查依赖
   pip list | grep python-docx
   pip list | grep openpyxl
   ```

3. **重新安装依赖**
   ```bash
   pip install -r backend/requirements.txt
   ```

### 问题: Excel 公式不计算

**症状:**
- 生成的 Excel 文件中公式显示为文本
- 或公式计算结果错误

**解决方案:**

1. **检查公式语法**
   - 确认公式使用正确的 Excel 语法
   - 使用英文逗号和括号

2. **手动刷新**
   - 打开 Excel 文件
   - 按 Ctrl+Shift+F9 强制重新计算

3. **检查公式缓存**
   - 有些公式需要打开文件后才会计算
   - 保存并重新打开文件

## 性能问题

### 问题: 应用运行缓慢

**症状:**
- 界面响应慢
- 对话生成速度慢
- 内存占用高

**解决方案:**

1. **检查内存使用**
   ```bash
   # Linux/macOS
   ps aux | grep sage
   
   # Windows (PowerShell)
   Get-Process sage | Select-Object MemoryUsage
   ```

2. **清理缓存**
   - 打开设置 → 高级
   - 点击"清理缓存"
   - 重启应用

3. **减少记忆数量**
   - 修剪旧记忆
   - 调整记忆保留策略

4. **检查后台进程**
   - 关闭不必要的技能
   - 禁用自动更新检查(临时)

### 问题: 磁盘空间不足

**症状:**
- 警告磁盘空间不足
- 无法保存新数据

**解决方案:**

1. **清理旧数据**
   ```bash
   # 查看数据目录大小
   du -sh ~/.config/sage  # Linux/macOS
   
   # Windows (PowerShell)
   Get-ChildItem %APPDATA%\sage -Recurse | Measure-Object -Property Length -Sum
   ```

2. **删除旧会话**
   - 打开记忆页面
   - 删除不需要的旧会话

3. **移动数据目录**
   - 关闭应用
   - 移动数据目录到新位置
   - 创建符号链接:
     ```bash
     ln -s /new/path/sage ~/.config/sage
     ```

## 日志和诊断

### 如何查看日志

1. **应用日志**
   - 位置:
     - Windows: `%APPDATA%\sage\logs\`
     - macOS: `~/Library/Application Support/sage/logs/`
     - Linux: `~/.config/sage/logs/`
   - 主要日志文件:
     - `main.log`: Electron 主进程日志
     - `renderer.log`: 前端日志
     - `backend.log`: Python 后端日志

2. **开发者工具**
   - 按 Ctrl+Shift+I (Windows/Linux) 或 Cmd+Option+I (macOS)
   - 查看 Console 标签页
   - 查看 Network 标签页(检查 API 请求)

3. **系统监控**
   ```bash
   # Linux/macOS
   top -p $(pgrep -f sage)
   
   # Windows (PowerShell)
   Get-Process sage | Select-Object CPU, MemoryUsage
   ```

### 如何提交 Bug 报告

访问 [GitHub Issues](https://github.com/oneMuggle/sage/issues/new) 并提供:

1. **问题描述**
   - 发生了什么
   - 预期行为
   - 实际行为

2. **复现步骤**
   - 详细的操作步骤
   - 是否总是可以复现

3. **环境信息**
   - 操作系统版本
   - Sage 版本
   - Python 版本(如适用)

4. **日志文件**
   - 附上相关的日志片段
   - 不要包含敏感信息(API Key 等)

5. **截图/录屏**
   - 如果可能,提供截图或录屏

## 联系支持

如果以上方案都无法解决问题:

1. **查看文档**
   - [完整文档](https://github.com/oneMuggle/sage/tree/main/docs/user-manual)
   - [GitHub Discussions](https://github.com/oneMuggle/sage/discussions)

2. **提交 Issue**
   - [GitHub Issues](https://github.com/oneMuggle/sage/issues/new)

3. **社区支持**
   - 加入 Discord/Slack 社区(如有)
   - 在 Discussions 中提问
