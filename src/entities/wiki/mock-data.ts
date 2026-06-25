// Mock Data - 模拟数据工厂（用于演示）
import type {
  LintItem,
  ReviewItem,
  ActivityItem,
  ResearchTask,
  FileNode,
} from '../../shared/types/wiki';

// Lint 模拟数据
export const mockLintItems: LintItem[] = [
  {
    id: 'lint-1',
    type: 'orphan',
    severity: 'warning',
    page: 'wiki/entities/legacy-api.md',
    message: '该页面没有被任何其他页面链接',
    suggestion: '考虑添加到相关页面的链接，或从 index.md 中移除',
  },
  {
    id: 'lint-2',
    type: 'broken-link',
    severity: 'warning',
    page: 'wiki/concepts/auth.md',
    message: '链接 [[missing-page]] 指向不存在的页面',
    suggestion: '创建 missing-page 或修正链接目标',
  },
  {
    id: 'lint-3',
    type: 'no-outlinks',
    severity: 'info',
    page: 'wiki/queries/faq.md',
    message: '该页面没有任何出链',
    suggestion: '添加相关链接以增强知识图谱连接',
  },
  {
    id: 'lint-4',
    type: 'semantic',
    severity: 'info',
    page: 'wiki/entities/user.md',
    message: '内容可能与 admin.md 重复',
    suggestion: '检查是否可以合并或建立交叉引用',
  },
];

// Review 模拟数据
export const mockReviewItems: ReviewItem[] = [
  {
    id: 'review-1',
    type: 'contradiction',
    title: 'API 认证方式矛盾',
    description: 'auth.md 说使用 OAuth2，但 api-guide.md 说使用 API Key',
    affectedPages: ['wiki/concepts/auth.md', 'wiki/guides/api-guide.md'],
    resolved: false,
    actions: [
      { id: 'research', label: '深度研究', type: 'research' },
      { id: 'open-auth', label: '打开 auth.md', type: 'open' },
      { id: 'open-guide', label: '打开 api-guide.md', type: 'open' },
      { id: 'dismiss', label: '忽略', type: 'dismiss' },
    ],
  },
  {
    id: 'review-2',
    type: 'duplicate',
    title: '重复的用户定义',
    description: 'user.md 和 account.md 包含相似的用户概念定义',
    affectedPages: ['wiki/entities/user.md', 'wiki/entities/account.md'],
    resolved: false,
    actions: [
      { id: 'merge', label: '合并页面', type: 'create' },
      { id: 'open-user', label: '打开 user.md', type: 'open' },
      { id: 'open-account', label: '打开 account.md', type: 'open' },
      { id: 'dismiss', label: '忽略', type: 'dismiss' },
    ],
  },
  {
    id: 'review-3',
    type: 'missing-page',
    title: '缺失的 API 端点页面',
    description: '多个页面引用了 [[api-endpoints]]，但该页面不存在',
    affectedPages: ['wiki/guides/api-guide.md', 'wiki/concepts/rest.md'],
    resolved: false,
    actions: [
      { id: 'create', label: '创建 api-endpoints.md', type: 'create' },
      { id: 'research', label: '深度研究', type: 'research' },
      { id: 'dismiss', label: '忽略', type: 'dismiss' },
    ],
  },
  {
    id: 'review-4',
    type: 'confirm',
    title: '确认分类：GraphQL 是 API 还是概念？',
    description: 'graphql.md 内容同时涉及 API 定义和概念解释',
    affectedPages: ['wiki/entities/graphql.md'],
    resolved: false,
    actions: [
      { id: 'move-api', label: '移动到 api/graphql.md', type: 'create' },
      { id: 'move-concept', label: '移动到 concepts/graphql.md', type: 'create' },
      { id: 'keep', label: '保持当前位置', type: 'dismiss' },
    ],
  },
  {
    id: 'review-5',
    type: 'suggestion',
    title: '建议：添加代码示例',
    description: 'authentication.md 缺少实际代码示例',
    affectedPages: ['wiki/concepts/authentication.md'],
    resolved: false,
    actions: [
      { id: 'research', label: '研究代码示例', type: 'research' },
      { id: 'open', label: '打开页面', type: 'open' },
      { id: 'dismiss', label: '忽略', type: 'dismiss' },
    ],
  },
];

// Sources 模拟数据
export const mockSourcesTree: FileNode[] = [
  {
    name: 'sources',
    path: 'raw/sources',
    is_dir: true,
    children: [
      {
        name: 'api-docs',
        path: 'raw/sources/api-docs',
        is_dir: true,
        children: [
          { name: 'rest-api.pdf', path: 'raw/sources/api-docs/rest-api.pdf', is_dir: false },
          { name: 'graphql-spec.md', path: 'raw/sources/api-docs/graphql-spec.md', is_dir: false },
        ],
      },
      {
        name: 'meeting-notes',
        path: 'raw/sources/meeting-notes',
        is_dir: true,
        children: [
          { name: '2024-01-15.md', path: 'raw/sources/meeting-notes/2024-01-15.md', is_dir: false },
          { name: '2024-01-22.md', path: 'raw/sources/meeting-notes/2024-01-22.md', is_dir: false },
        ],
      },
      { name: 'architecture.docx', path: 'raw/sources/architecture.docx', is_dir: false },
      { name: 'user-manual.pdf', path: 'raw/sources/user-manual.pdf', is_dir: false },
    ],
  },
];

// Activity 模拟数据
export const mockActivities: ActivityItem[] = [
  {
    id: 'activity-1',
    type: 'ingest',
    status: 'done',
    startedAt: Date.now() - 3600000,
    completedAt: Date.now() - 3500000,
    filesWritten: ['wiki/entities/api.md', 'wiki/concepts/rest.md'],
  },
  {
    id: 'activity-2',
    type: 'lint',
    status: 'running',
    startedAt: Date.now() - 60000,
  },
  {
    id: 'activity-3',
    type: 'query',
    status: 'done',
    startedAt: Date.now() - 7200000,
    completedAt: Date.now() - 7100000,
    filesWritten: ['wiki/queries/oauth2-vs-jwt.md'],
  },
  {
    id: 'activity-4',
    type: 'ingest',
    status: 'error',
    startedAt: Date.now() - 86400000,
    error: 'LLM 请求超时',
  },
];

// Research 模拟数据
export const mockResearchTasks: ResearchTask[] = [
  {
    id: 'research-1',
    topic: 'OAuth2 vs JWT 对比',
    status: 'done',
    webResults: [
      {
        title: 'OAuth 2.0 vs JWT',
        url: 'https://example.com/oauth-jwt',
        snippet: 'OAuth2 和 JWT 是两种不同的...',
      },
      {
        title: 'Authentication Best Practices',
        url: 'https://example.com/auth-best',
        snippet: '现代应用推荐使用...',
      },
    ],
    synthesis:
      '# OAuth2 vs JWT\n\n## 概述\n\nOAuth2 和 JWT 是两种常用的认证/授权机制，但它们解决不同的问题。\n\n## OAuth2\n\nOAuth2 是一个授权框架...',
    savedPath: 'wiki/queries/oauth2-vs-jwt.md',
  },
  {
    id: 'research-2',
    topic: '微服务架构最佳实践',
    status: 'searching',
    webResults: [],
    synthesis: '',
  },
];
