# 浏览器环境诊断

> 本文档面向 Sage 桌面端用户，说明如何使用浏览器环境诊断功能。

## 1. 功能简介

Sage 需要浏览器来完成网页访问和登录态保持。在 Windows 7 等老旧系统上，浏览器可能无法正常安装或运行。

**浏览器环境诊断**功能会自动检测：

- 本机是否安装了可用的浏览器（Chrome / Edge / Firefox）
- Windows 7 必备补丁是否已安装
- 浏览器启动所需的前置条件是否满足

## 2. 如何查看诊断结果

1. 打开 Sage 桌面端
2. 进入 **设置**（托盘图标右键 → 设置）
3. 选择 **网络** 标签页
4. 向下滚动到 **浏览器环境** 区块

诊断结果会自动加载，显示：

- **推荐浏览器**：当前环境最适合使用的浏览器类型
- **检查项列表**：每项检查的状态（通过 / 警告 / 失败 / 不适用）
- **修复建议**：失败项会提供下载链接或操作指引

## 3. 检查项说明

| 检查项 | 含义 | 适用系统 |
|--------|------|----------|
| Chrome 可执行文件 | 检测 Chrome / Edge / Chromium 是否已安装 | 所有 |
| Firefox 可执行文件 | 检测 Firefox 是否已安装 | 所有 |
| Windows 7 SP1 | 检测是否安装了 SP1 服务包 | 仅 Windows |
| KB4474419 SHA-2 补丁 | 检测代码签名所需的 SHA-2 补丁 | 仅 Windows 7 |
| VC++ 2019 Redistributable | 检测 C++ 运行时库 | 仅 Windows |
| 浏览器数据目录可写 | 检测 `~/.sage/browser-data/` 是否可写 | 所有 |
| CDP 握手 | 检测 Chrome DevTools Protocol 握手是否成功 | 所有 |

## 4. Windows 7 用户必读

Windows 7 SP1 用户需要安装以下补丁才能使用浏览器功能：

### 4.1 KB4474419（SHA-2 代码签名补丁）

**必须安装**。没有此补丁，Chrome 109 安装包无法验证签名，会报"不是有效的 Win32 应用程序"。

**下载**：[Microsoft Update Catalog - KB4474419](https://www.catalog.update.microsoft.com/Search.aspx?q=KB4474419)

选择与您系统匹配的版本：
- 64 位系统：`windows6.1-kb4474419-v2-x64.msu`
- 32 位系统：`windows6.1-kb4474419-v2-x86.msu`

### 4.2 VC++ 2019 Redistributable

**必须安装**。Chrome 109 依赖此运行时库。

**下载**：[Microsoft - VC++ 2019 Redistributable](https://aka.ms/vs/16/release/vc_redist.x64.exe)

选择 `x64` 版本（64 位系统）或 `x86` 版本（32 位系统）。

### 4.3 Firefox 115 ESR（备选方案）

如果 Chrome 无法安装，可以使用 Firefox 115 ESR。Mozilla 官方支持 Firefox 115 ESR 在 Windows 7 上运行到 **2027 年 3 月**。

**下载**：[Mozilla Firefox 企业版](https://www.mozilla.org/firefox/enterprise/)

选择"Windows 64 位"或"Windows 32 位"安装包。

## 5. 重新检测

如果安装了补丁或浏览器后，诊断结果没有自动更新：

1. 点击 **重新检测** 按钮
2. 等待几秒钟，结果会自动刷新

## 6. 常见问题

### 6.1 所有检查项都显示"不适用"

这通常发生在非 Windows 系统（Linux / macOS）上。Windows 专属检查项（SP1、KB4474419、VC++ 2019）在非 Windows 系统上显示为"不适用"是正常的。

### 6.2 推荐浏览器显示"—"

表示当前没有检测到可用的浏览器。请：

1. 安装 Chrome、Edge 或 Firefox
2. 点击"重新检测"

### 6.3 CDP 握手失败

可能原因：

- 浏览器正在运行（占用端口）
- 防火墙阻止了本地连接
- 浏览器配置文件损坏

**解决方法**：

1. 关闭所有浏览器窗口
2. 删除 `~/.sage/browser-data/` 目录
3. 重新点击"重新检测"

### 6.4 Windows 7 上 Chrome 安装失败

即使安装了 KB4474419 和 VC++ 2019，Chrome 仍可能因以下原因失败：

- **系统未更新到 SP1**：必须先安装 SP1
- **缺少其他补丁**：某些环境需要 KB4490628 等额外补丁
- **组策略限制**：企业环境可能禁止安装

**建议**：使用 Firefox 115 ESR 作为替代方案。

## 7. 技术细节

开发者如需了解诊断功能的实现细节，请参阅：

- 技术文档：`docs/technical/76-multi-browser-support.md`
- 实施计划：`docs/plans/2026-09-17_multi-browser-support.md`
- CLI 脚本：`python scripts/check_browser_environment.py`
