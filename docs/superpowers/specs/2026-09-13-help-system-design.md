# Help System Design

> **Date:** 2026-09-13  
> **Status:** Approved  
> **Branch:** feat/help-system  
> **Target:** main + release/win7 (TBD)

---

## 1. Overview

### 1.1 Background

Sage 桌面应用目前缺乏应用内的帮助系统、关于页面和更新日志查看器。用户无法快速了解软件信息、学习使用方法或查看版本更新内容。

### 1.2 Goals

- **帮助中心**: 让用户能快速上手、理解功能、故障排除
- **关于页面**: 展示应用愿景、设计理念、贡献者信息
- **更新日志**: 让用户了解每个版本的功能变化和修复

### 1.3 Non-Goals

- 不替代现有的 `docs/user-manual/` 文档系统
- 不提供复杂的搜索功能(Phase 1)
- 不支持多语言(Phase 1)

---

## 2. Architecture

### 2.1 High-Level Design

采用 **统一帮助系统** 架构:单一 `/help` 路由,包含三个标签页(帮助/关于/更新日志)。

```
┌──────────────────────────────────────────────────────────┐
│  Help Page (/help)                                       │
├──────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────┐ │
│  │  帮助  │  关于  │  更新日志                         │ │ ← TabNav
│  └────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────┐ │
│  │  [Tab Content]                                     │ │
│  │  - HelpTab / AboutTab / ChangelogTab               │ │
│  └────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────┐ │
│  │  📖 完整文档  │  💬 反馈问题  │  🔗 GitHub         │ │ ← Footer
│  └────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Component Hierarchy

```
src/pages/Help/
  ├── index.tsx              # Help 页面入口
  ├── HelpTab.tsx            # 帮助标签页
  ├── AboutTab.tsx           # 关于标签页
  └── ChangelogTab.tsx       # 更新日志标签页

src/widgets/help/
  ├── HelpSidebar.tsx        # 帮助侧边栏(目录导航)
  ├── HelpContent.tsx        # 帮助内容渲染器(markdown)
  └── HelpFooter.tsx         # 底部链接

src/content/
  ├── help/
  │   ├── getting-started.md # 快速上手
  │   ├── faq.md            # 常见问题
  │   └── troubleshooting.md # 故障排除
  └── about/
      ├── vision.ts         # 应用愿景
      ├── philosophy.ts     # 设计理念
      └── contributors.json # 贡献者列表

src/lib/
  └── changelogParser.ts    # CHANGELOG 解析器
```

### 2.3 Routing & Navigation

```typescript
// src/App.tsx
<Route path="help" element={<Help />} />

// 访问方式
// 1. 侧边栏"帮助"按钮 → navigate('/help')
// 2. 快捷键 F1 → navigate('/help')
// 3. 系统菜单"帮助" → navigate('/help')
```

### 2.4 Data Flow

#### HelpTab

```typescript
// 内置内容(Vite ?raw 导入)
import gettingStarted from '../content/help/getting-started.md?raw';

// user-manual 内容(IPC 读取)
window.helpAPI.readUserManual('01-desktop.md')
  .then(content => renderMarkdown(content));
```

#### AboutTab

```typescript
// 静态内容
import { VISION, PHILOSOPHY } from '../content/about/vision';
import contributors from '../content/about/contributors.json';

// 动态数据
const version = __APP_VERSION__;
const electronVersion = process.versions.electron;
```

#### ChangelogTab

```typescript
// IPC 读取 CHANGELOG.md
window.changelogAPI.read().then(parseChangelog);

// 解析和分类
parseChangelog(markdown): ChangelogEntry[]
generateSummary(entries): { currentVersion, recentVersions, highlights }
```

---

## 3. Detailed Design

### 3.1 HelpTab

#### Layout

```
┌────────────────┬─────────────────────────────────────────┐
│  📚 目录       │  # 快速上手                             │
│                │                                         │
│  ▶ 快速上手    │  欢迎使用 Sage!本节将帮助你...         │
│  ▶ 核心功能    │                                         │
│    ├ 对话      │  ## 第一步: 配置 API                    │
│    ├ 记忆      │  1. 打开设置页面                        │
│    └ 技能      │  2. 配置 API 端点                       │
│  ▶ 高级功能    │                                         │
│  ▶ 常见问题    │  [渲染的 markdown 内容]                 │
│  ▶ 故障排除    │                                         │
│                │                                         │
│  ────────────  │                                         │
│  📖 更多文档   │                                         │
│  ├ 桌面使用    │                                         │
│  ├ 记忆系统    │                                         │
│  └ Office     │                                         │
└────────────────┴─────────────────────────────────────────┘
```

#### Interaction

- 左侧目录可折叠(▶/▼)
- 点击目录项 → 右侧内容滚动到对应锚点
- 右侧内容支持 markdown 渲染(代码高亮、表格、链接)
- 滚动时左侧目录自动高亮当前章节

#### Implementation

```typescript
interface HelpSidebarProps {
  items: HelpItem[];
  activeItem: string;
  onItemClick: (id: string) => void;
}

interface HelpItem {
  id: string;
  title: string;
  children?: HelpItem[];
  type: 'builtin' | 'user-manual';
  filename?: string; // for user-manual
}

function HelpSidebar({ items, activeItem, onItemClick }: HelpSidebarProps) {
  return (
    <nav className="w-60 border-r border-border overflow-y-auto">
      {items.map(item => (
        <SidebarItem
          key={item.id}
          item={item}
          active={activeItem === item.id}
          onClick={() => onItemClick(item.id)}
        />
      ))}
    </nav>
  );
}

function HelpContent({ content }: { content: string }) {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-4">
      <ReactMarkdown
        rehypePlugins={[rehypeKatex, rehypeHighlight]}
        components={{
          code: CodeBlock,
          table: Table,
          a: Link,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
```

### 3.2 AboutTab

#### Layout

```
┌──────────────────────────────────────────────────────────┐
│           [Sage Logo]                                    │
│           Sage v0.4.9-alpha.42                           │
│           记忆型 AI 桌面助手                              │
├──────────────────────────────────────────────────────────┤
│  🎯 应用愿景                                             │
│  Sage 是一款轻量级 AI 桌面助手...                        │
├──────────────────────────────────────────────────────────┤
│  💡 设计理念                                             │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ 记忆优先     │  │ 渐进式演化   │                     │
│  │ 所有交互默认 │  │ Agent 可从   │                     │
│  │ 持久化       │  │ 错误中学习   │                     │
│  └──────────────┘  └──────────────┘                     │
├──────────────────────────────────────────────────────────┤
│  👥 贡献者                                               │
│  核心开发: Author Name                                   │
│  贡献者: Name 1, Name 2                                  │
│  特别感谢: React, Electron, FastAPI                      │
├──────────────────────────────────────────────────────────┤
│  ℹ️ 系统信息                                             │
│  版本: 0.4.9-alpha.42                                    │
│  Electron: 21.4.4                                        │
│  Node.js: 18.x                                           │
│  Python: 3.10+                                           │
│  许可证: MIT                                             │
└──────────────────────────────────────────────────────────┘
```

#### Implementation

```typescript
function AboutTab() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <BrandHeader />
      <VisionSection />
      <PhilosophySection />
      <ContributorsSection />
      <SystemInfoSection />
    </div>
  );
}

function BrandHeader() {
  return (
    <div className="text-center mb-8">
      <BrandLogo size="lg" />
      <h1 className="text-2xl font-bold mt-4">Sage v{__APP_VERSION__}</h1>
      <p className="text-text-secondary mt-2">记忆型 AI 桌面助手</p>
    </div>
  );
}

function SystemInfoSection() {
  const info = [
    { label: '版本', value: __APP_VERSION__ },
    { label: 'Electron', value: process.versions.electron },
    { label: 'Node.js', value: process.versions.node },
    { label: 'Python', value: '3.10+' },
    { label: '许可证', value: 'MIT' },
  ];
  
  return (
    <section>
      <h2>ℹ️ 系统信息</h2>
      <dl>
        {info.map(({ label, value }) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
```

### 3.3 ChangelogTab

#### Layout

```
┌──────────────────────────────────────────────────────────┐
│  当前版本: v0.4.9-alpha.42  📅 2026-09-13               │
├──────────────────────────────────────────────────────────┤
│  🚀 重大功能 (5)                                         │
│  ▼  Office 对标系列                                      │
│     • journal 接入引用引擎                               │
│     • Excel 图标集条件格式                               │
│     ...                                                  │
├──────────────────────────────────────────────────────────┤
│  ✨ 改进 (3)                                             │
│  • Word @ 摘要优化                                       │
│  • Excel 摘要优化                                        │
│  ...                                                     │
├──────────────────────────────────────────────────────────┤
│  🐛 修复 (2)                                             │
│  • PDF 生成中文输出为空白                                │
│  • Excel 编辑后公式缓存值丢失                            │
├──────────────────────────────────────────────────────────┤
│  📜 历史版本                                             │
│  ▼ v0.4.9-alpha.41  2026-09-11                          │
│     🔌 可插拔更新源系统 Phase 1-4 完整闭环               │
│  ▼ v0.4.9-alpha.40  2026-09-10                          │
│     🔧 启动诊断系统                                      │
│  [查看更多...]                                           │
└──────────────────────────────────────────────────────────┘
```

#### Implementation

```typescript
// src/lib/changelogParser.ts
interface ChangelogEntry {
  version: string;
  date: string;
  highlights: {
    major: string[];      // feat:
    improvements: string[]; // perf:, refactor:
    fixes: string[];      // fix:
  };
  raw: string;
}

function parseChangelog(markdown: string): ChangelogEntry[] {
  const entries: ChangelogEntry[] = [];
  const versionRegex = /## \[v?([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})/g;
  const sections = markdown.split(versionRegex);
  
  for (let i = 1; i < sections.length; i += 3) {
    const version = sections[i];
    const date = sections[i + 1];
    const content = sections[i + 2];
    
    const highlights = {
      major: extractSection(content, 'Added'),
      improvements: extractSection(content, 'Changed'),
      fixes: extractSection(content, 'Fixed'),
    };
    
    entries.push({ version, date, highlights, raw: content });
  }
  
  return entries;
}

function generateSummary(entries: ChangelogEntry[]) {
  const currentVersion = entries[0];
  const recentVersions = entries.slice(1, 4);
  
  const highlightsByCategory = {
    major: currentVersion.highlights.major,
    improvements: currentVersion.highlights.improvements,
    fixes: currentVersion.highlights.fixes,
  };
  
  return { currentVersion, recentVersions, highlightsByCategory };
}

// src/pages/Help/ChangelogTab.tsx
function ChangelogTab() {
  const { data: changelog, isLoading } = useQuery({
    queryKey: ['changelog'],
    queryFn: () => window.changelogAPI.read(),
  });
  
  if (isLoading) return <LoadingSpinner />;
  
  const entries = parseChangelog(changelog);
  const summary = generateSummary(entries);
  
  return (
    <div className="px-6 py-4">
      <CurrentVersionSummary entry={summary.currentVersion} />
      <HighlightsByCategory highlights={summary.highlightsByCategory} />
      <RecentVersions versions={summary.recentVersions} />
    </div>
  );
}
```

### 3.4 IPC Bridge

```typescript
// electron/preload.ts
contextBridge.exposeInMainWorld('helpAPI', {
  readUserManual: (filename: string): Promise<string> => {
    return ipcRenderer.invoke('help:read-user-manual', filename);
  },
  prefetch: (filename: string): Promise<void> => {
    return ipcRenderer.invoke('help:prefetch', filename);
  },
});

contextBridge.exposeInMainWorld('changelogAPI', {
  read: (): Promise<string> => {
    return ipcRenderer.invoke('changelog:read');
  },
});

// electron/main.ts
ipcMain.handle('help:read-user-manual', async (_event, filename: string) => {
  const filePath = path.join(__dirname, '..', 'docs', 'user-manual', filename);
  return fs.readFile(filePath, 'utf-8');
});

ipcMain.handle('changelog:read', async () => {
  const filePath = path.join(__dirname, '..', 'CHANGELOG.md');
  return fs.readFile(filePath, 'utf-8');
});
```

### 3.5 Keyboard Shortcuts

```typescript
// src/App.tsx
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    if (e.key === 'F1') {
      e.preventDefault();
      navigate('/help');
    }
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, [navigate]);
```

---

## 4. Testing Strategy

### 4.1 Unit Tests

```typescript
// src/lib/__tests__/changelogParser.test.ts
describe('changelogParser', () => {
  it('parses version headers correctly', () => {
    const markdown = '## [v0.4.9-alpha.42] - 2026-09-13\n\n### Added\n- Feature 1';
    const entries = parseChangelog(markdown);
    expect(entries[0].version).toBe('0.4.9-alpha.42');
    expect(entries[0].date).toBe('2026-09-13');
  });

  it('categorizes changes by type', () => {
    const markdown = `
## [v0.4.9] - 2026-09-13
### Added
- feat: new feature
### Changed
- perf: optimization
### Fixed
- fix: bug fix
`;
    const entries = parseChangelog(markdown);
    expect(entries[0].highlights.major).toHaveLength(1);
    expect(entries[0].highlights.improvements).toHaveLength(1);
    expect(entries[0].highlights.fixes).toHaveLength(1);
  });
});
```

### 4.2 Integration Tests

```typescript
// electron/__tests__/helpIPC.test.ts
describe('help IPC handlers', () => {
  it('reads user manual file', async () => {
    const content = await ipcMain.invoke('help:read-user-manual', '01-desktop.md');
    expect(content).toContain('桌面使用');
  });

  it('returns error for non-existent file', async () => {
    await expect(
      ipcMain.invoke('help:read-user-manual', 'nonexistent.md')
    ).rejects.toThrow();
  });
});
```

### 4.3 E2E Tests

```typescript
// e2e/help-system.e2e.ts
test.describe('Help System', () => {
  test('opens help page via F1 shortcut', async ({ page }) => {
    await page.keyboard.press('F1');
    await expect(page.locator('[data-testid="help-page"]')).toBeVisible();
  });

  test('navigates between tabs', async ({ page }) => {
    await page.goto('/help');
    await page.click('[role="tab"]:has-text("关于")');
    await expect(page.locator('[data-testid="about-tab"]')).toBeVisible();
  });

  test('loads user manual content', async ({ page }) => {
    await page.goto('/help');
    await page.click('text=记忆系统');
    await expect(page.locator('[data-testid="help-content"]')).toContainText('记忆系统');
  });
});
```

---

## 5. Performance Considerations

### 5.1 Virtual Scrolling

```typescript
// 使用 @tanstack/react-virtual 渲染长 CHANGELOG
import { useVirtualizer } from '@tanstack/react-virtual';

function ChangelogList({ entries }: { entries: ChangelogEntry[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 200,
  });

  return (
    <div ref={parentRef} style={{ height: '600px', overflow: 'auto' }}>
      <div style={{ height: `${virtualizer.getTotalSize()}px` }}>
        {virtualizer.getVirtualItems().map((virtualRow) => (
          <ChangelogEntry key={virtualRow.key} entry={entries[virtualRow.index]} />
        ))}
      </div>
    </div>
  );
}
```

### 5.2 Markdown Rendering Optimization

```typescript
// 使用 useMemo 缓存解析结果
const renderedContent = useMemo(() => {
  return <ReactMarkdown rehypePlugins={[rehypeKatex, rehypeHighlight]}>{content}</ReactMarkdown>;
}, [content]);

// 懒加载 rehype 插件
const rehypeHighlight = lazy(() => import('rehype-highlight'));
```

### 5.3 Content Prefetching

```typescript
// 应用启动时预加载帮助内容
useEffect(() => {
  const recentFiles = localStorage.getItem('help:recent-files');
  if (recentFiles) {
    JSON.parse(recentFiles).forEach((file: string) => {
      window.helpAPI.prefetch(file);
    });
  }
}, []);
```

---

## 6. Accessibility

```typescript
// 语义化标签
<nav aria-label="帮助目录">...</nav>
<main aria-label="帮助内容">...</main>

// 键盘导航
<button 
  role="tab"
  aria-selected={activeTab === 'help'}
  onKeyDown={(e) => {
    if (e.key === 'ArrowRight') setActiveTab('about');
    if (e.key === 'ArrowLeft') setActiveTab('changelog');
  }}
>
  帮助
</button>

// 焦点管理
useEffect(() => {
  if (activeTab === 'help') {
    sidebarRef.current?.focus();
  }
}, [activeTab]);

// 屏幕阅读器
<div aria-live="polite">
  {loading && '加载中...'}
  {error && `错误: ${error}`}
</div>
```

---

## 7. Implementation Plan

### Phase 1: 基础架构 (1-2 天)
- [ ] 创建路由和页面组件骨架
- [ ] 实现 TabNav 和基础布局
- [ ] 集成到侧边栏导航
- [ ] 添加 F1 快捷键

### Phase 2: HelpTab (2-3 天)
- [ ] 编写内置帮助内容(getting-started.md, faq.md)
- [ ] 实现 HelpSidebar 目录导航
- [ ] 实现 HelpContent markdown 渲染
- [ ] 添加 IPC 读取 user-manual
- [ ] 实现滚动联动(目录高亮)

### Phase 3: AboutTab (1 天)
- [ ] 设计品牌展示布局
- [ ] 编写愿景和设计理念内容
- [ ] 收集贡献者信息
- [ ] 显示系统信息(版本、Electron、Node 等)

### Phase 4: ChangelogTab (2-3 天)
- [ ] 实现 CHANGELOG.md 读取(IPC)
- [ ] 实现 changelogParser 解析器
- [ ] 实现智能摘要生成
- [ ] 设计 UI 布局(分类展示、折叠/展开)
- [ ] 添加虚拟滚动优化

### Phase 5: 测试与优化 (1-2 天)
- [ ] 单元测试(changelogParser, 组件)
- [ ] 集成测试(IPC 调用)
- [ ] E2E 测试(用户流程)
- [ ] 性能优化(虚拟滚动、预加载)
- [ ] 可访问性检查

**Total:** 7-11 天

---

## 8. Win7 Branch Alignment

### 8.1 Strategy

该功能需要在 main 和 release/win7 两个分支都实现,因为:
- 用户帮助是核心功能,两个分支的用户都需要
- 代码不涉及平台特定依赖
- UI 组件使用标准 React,无 Electron 版本限制

### 8.2 Sync Plan

1. 在 main 分支完成开发和测试
2. 创建 PR 并合并到 main
3. Cherry-pick 功能性 commit 到 release/win7
4. 解决可能的冲突(版本号、依赖版本)
5. 在 win7 分支测试验证
6. 打 tag 发布

### 8.3 Potential Conflicts

- `package.json` version 不同
- `docs/user-manual/` 内容可能不同步
- 依赖版本差异(React、Electron)

---

## 9. Future Enhancements

### Phase 2 (Post-MVP)

- [ ] 搜索功能(全文搜索帮助内容)
- [ ] 多语言支持(i18n)
- [ ] 视频帮助教程
- [ ] 交互式教程(onboarding wizard)
- [ ] 反馈系统(用户可以直接提交反馈)
- [ ] 离线帮助内容缓存

---

## 10. Success Metrics

- **用户发现率**: 80%+ 用户能在 1 分钟内找到帮助入口
- **内容覆盖率**: 90%+ 核心功能有帮助文档
- **用户满意度**: 帮助系统评分 4/5+
- **更新日志阅读率**: 50%+ 用户在更新后查看更新日志

---

## References

- [Sage User Manual](../../docs/user-manual/)
- [CHANGELOG.md](../../CHANGELOG.md)
- [ShortcutHelpOverlay](../../src/widgets/system/ShortcutHelpOverlay.tsx)
- [UpdateDialog](../../src/components/UpdateDialog.tsx)
