# 16 — 额外访问路径（Allowed Paths）

## 什么是 Allowed Paths？

默认情况下，Sage 只能访问当前项目 workspace 内的文件。

**Allowed Paths** 让你配置额外的"只读访问规则"——agent 可以读取这些路径下的文件，
但**不能写入**（写入仍限于 workspace）。

典型场景：
- 让 agent 读取 `~/Documents/` 下的参考资料
- 让 agent 查看 `/tmp/` 下的临时数据
- 让 agent 访问共享目录中的文件

## 如何添加 Allowed Path

1. 打开左侧栏的 **项目设置**（齿轮图标）
2. 找到 **额外访问路径** 区域
3. 点击 **+ 添加路径**
4. 输入路径规则（支持通配符）
5. 点击 **保存**

### 路径规则格式

| 规则 | 含义 | 示例 |
|------|------|------|
| `~/Documents/**` | Documents 及所有子文件 | 常用参考资料目录 |
| `~/Desktop/*.pdf` | 桌面所有 PDF | 临时查看 PDF |
| `/tmp/scratch/*` | scratch 直接子文件 | 临时数据 |
| `~/projects/shared` | 整个目录 | 共享项目目录 |

**提示：**
- `~` 代表你的 home 目录（如 `/home/user` 或 `C:\Users\YourName`）
- `**` 匹配所有层级子目录
- `*` 只匹配当前层级

## 首次访问未授权路径

当 agent 试图访问不在 workspace 也不在 allowed_paths 中的文件时，会弹出审批对话框：

```
🔐 访问授权请求

工具: read_file
Agent 想读取: /home/user/Desktop/报告.txt

[拒绝]  [允许]  [项目级允许]
```

三个选项：
- **拒绝** — 本次拒绝，agent 无法访问
- **允许** — 本次允许，下次还会询问
- **项目级允许** — 将该路径加入 allowed_paths，以后不再询问

## 注意事项

1. **只读**：allowed_paths 内的文件只能读取，不能修改或删除
2. **持久化**：通过"项目级允许"添加的规则会保存在项目设置中
3. **跨平台**：路径规则在 Windows/macOS/Linux 上都能正常工作
4. **安全**：agent 无法绕过 allowed_paths 限制访问其他路径
