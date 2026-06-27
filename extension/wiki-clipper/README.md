# Sage Wiki Clipper

Chrome 扩展，用于将网页内容保存到 Sage Wiki 知识库。

## 功能

- 📄 一键提取网页主要内容（使用 Readability.js）
- 🔄 自动转换为 Markdown 格式（使用 Turndown.js）
- 💾 保存到指定的 Wiki 项目
- 🤖 支持自动 Ingest（使用 LLM 提取关键信息）
- 📝 支持添加备注

## 安装

1. 打开 Chrome 浏览器
2. 访问 `chrome://extensions/`
3. 启用"开发者模式"
4. 点击"加载已解压的扩展程序"
5. 选择 `extension/wiki-clipper` 目录

## 依赖库

需要下载以下库到 `lib/` 目录：

- [Readability.js](https://github.com/mozilla/readability) - Mozilla 的内容提取库
- [Turndown.js](https://github.com/domchristie/turndown) - HTML 到 Markdown 转换器

```bash
cd extension/wiki-clipper/lib
curl -O https://raw.githubusercontent.com/mozilla/readability/main/Readability.js
curl -O https://raw.githubusercontent.com/domchristie/turndown/master/dist/turndown.js
```

## 使用方法

1. 在 Sage Wiki 后端运行后（默认 `http://127.0.0.1:8765`）
2. 访问任意网页
3. 点击 Chrome 工具栏中的 Sage Wiki Clipper 图标
4. 配置：
   - **API URL**：后端 API 地址（默认 `http://127.0.0.1:8765/api/v1`）
   - **项目路径**：Wiki 项目的根目录
   - **页面标题**：可自定义
   - **备注**：可添加额外说明
   - **自动 Ingest**：是否使用 LLM 提取关键信息
5. 点击"保存到 Wiki"按钮

## 后端 API

扩展通过以下端点保存内容：

```
POST /api/v1/wiki/clip
```

请求体：
```json
{
  "title": "页面标题",
  "url": "https://example.com",
  "content": "Markdown 内容",
  "project_path": "/path/to/wiki",
  "notes": "备注",
  "auto_ingest": true
}
```

## 文件结构

```
extension/wiki-clipper/
├── manifest.json      # Chrome 扩展配置
├── popup.html         # 弹出窗口 UI
├── popup.js           # 弹出窗口逻辑
├── content.js         # 内容脚本（提取网页内容）
├── background.js      # 后台 Service Worker
├── lib/               # 第三方库
│   ├── readability.js
│   └── turndown.js
└── icons/             # 图标
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

## 开发

修改代码后，在 `chrome://extensions/` 页面点击"重新加载"按钮即可更新。

## 许可

MIT
