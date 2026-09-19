# Sage 设置页治理设计方案

**日期**: 2026-09-19  
**状态**: Draft  
**范围**: P0 + P1 + P2（含存储契约统一）

## 1. 背景与问题

当前 Sage 设置页存在以下问题：

### 1.1 信息架构问题
- **通用 Tab 过载**: 主题、语言、字体、流式、时区、记忆、托盘、演示模式、权限、Hooks、花费、诊断、网关等 20+ 项混在一起
- **作用域不清晰**: 全局设置、会话设置、Run 级设置、端点级设置混在一起
- **高级项未折叠**: 编排 15 个参数、网络白名单、Runtime 探测等普通用户不需要的项平铺显示
- **搜索结果只跳 Tab**: 不能定位到具体控件

### 1.2 配置契约问题
- **四套存储**: `app_settings` blob / preferences KV / Electron JSON / localStorage 各自为政
- **生效时机不统一**: 有些即时、有些下次请求、有些需要重启，但没有标注
- **默认值说明不准确**: `maxContext`/`autoContext` 交互混乱、Temperature 范围与描述不符
- **输入约束缺失**: `maxConcurrentSubagents=0` 会导致编排挂死

### 1.3 覆盖缺口
- **更新页缺 6 个配置**: `rollbackWindowDays` / `autoRollbackThreshold` / `checkIntervalHours` / `updateServerUrl` / `enableTelemetry` / `cacheRetentionDays`
- **内部参数无 UI**: `bash_config` / `compact_threshold_tokens` / `topic_detection` 等

### 1.4 测试缺口
- 没有统一的设置元数据注册表
- 没有默认值契约测试
- 没有生效时机验证

## 2. 目标

### 2.1 用户体验目标
- 每个设置项都有明确的**作用域**、**生效时机**、**默认值**、**风险等级**
- 基础用户只看基础设置，高级用户可展开高级设置
- 搜索结果可以定位并高亮具体控件
- 敏感操作（删除、重置、网关）有明确的风险提示

### 2.2 技术目标
- 建立统一的设置元数据注册表 `settingsRegistry`
- 自动生成搜索索引、默认值说明、生效时机标签
- 保存失败有明确的错误反馈
- 每个设置项都有契约测试

### 2.3 信息架构目标
- 从 10+ Tab 收敛为 7 个主类
- 每个主类分为"基础"和"高级折叠"
- 高风险操作单独分组

## 3. 目标信息架构

```
设置
├── 1. 基础
│   ├── 外观（主题/语言/字体）
│   ├── 对话行为（流式/时区/托盘）
│   └── 确认与通知
│
├── 2. 模型与端点
│   ├── 端点管理
│   ├── 默认 Chat 模型
│   ├── Vision/Embedding/TTS/ASR/Image Gen
│   ├── Temperature（带准确描述）
│   ├── 上下文窗口（自动/手动，显示当前值）
│   └── Fallback 模型
│
├── 3. 记忆与知识
│   ├── 自动记忆
│   ├── 记忆删除确认
│   ├── 嵌入器（字面/语义/API，显示当前状态）
│   ├── 附件 RAG
│   ├── 上下文轮数
│   ├── 话题检测（高级折叠）
│   ├── 记忆固化
│   └── 备份/导入/导出/恢复
│
├── 4. 工具与连接
│   ├── MCP
│   ├── Hooks
│   ├── 网关（Telegram/Discord/Slack）
│   ├── 网站凭据
│   ├── 搜索引擎
│   └── 工具权限
│
├── 5. 网络与安全
│   ├── 网络模式
│   ├── 域名白名单
│   ├── TLS 例外
│   ├── HTTP/SOCKS 代理
│   ├── 权限模式
│   └── 审批规则
│
├── 6. 编排与开发者
│   ├── 基础（计划前置/并发/超时/审批/预算）
│   ├── 高级折叠（结果上限/重派链/Scratch/Worktree/详细迭代）
│   └── Runtime 探测（开发者专用）
│
└── 7. 更新
    ├── 基础（策略/通道/检查）
    ├── 安全与回滚（折叠）
    └── 网络与隐私（折叠）
```

## 4. 设置元数据模型

### 4.1 TypeScript 接口

```typescript
// src/entities/setting/metadata.ts

export type SettingScope = 
  | 'global'      // 全局生效
  | 'session'     // 当前会话
  | 'run'         // 当前 Run
  | 'endpoint'    // 端点级
  | 'model';      // 模型级

export type StorageBackend = 
  | 'app_settings'    // 后端 app_settings blob
  | 'preference'      // 后端 preferences KV
  | 'electron'        // Electron 配置文件
  | 'local';          // 前端 localStorage

export type ApplyMode = 
  | 'immediate'       // 立即生效
  | 'next-request'    // 下次请求
  | 'next-run'        // 下次 Run
  | 'reload-model'    // 重新加载模型
  | 'restart'         // 重启应用
  | 'save-only';      // 仅保存，不改变运行态

export type Visibility = 
  | 'basic'           // 基础设置
  | 'advanced'        // 高级设置（折叠）
  | 'developer'       // 开发者专用
  | 'internal';       // 内部，不暴露

export type RiskLevel = 
  | 'low'             // 无风险
  | 'medium'          // 可能影响功能
  | 'high';           // 不可逆或需要重启

export interface SettingMetadata {
  key: string;
  label: string;
  labelEn?: string;
  description: string;
  descriptionEn?: string;
  
  scope: SettingScope;
  storage: StorageBackend;
  storageKey?: string;  // 与 key 不同时的实际存储 key
  
  defaultValue: unknown;
  
  applyMode: ApplyMode;
  visibility: Visibility;
  riskLevel: RiskLevel;
  
  // 输入约束
  constraints?: {
    type: 'string' | 'number' | 'boolean' | 'enum' | 'json';
    min?: number;
    max?: number;
    options?: Array<{ value: string; label: string }>;
    pattern?: string;
  };
  
  // 依赖关系
  dependsOn?: string[];  // 依赖的其他设置 key
  affects?: string[];    // 影响的其他设置
  
  // 验证
  validate?: (value: unknown) => string | null;  // 返回错误信息或 null
}
```

### 4.2 注册表示例

```typescript
// src/entities/setting/settingsRegistry.ts

import type { SettingMetadata } from './metadata';

export const settingsRegistry: Record<string, SettingMetadata> = {
  'streaming': {
    key: 'streaming',
    label: '流式输出',
    labelEn: 'Streaming',
    description: '逐字显示 AI 回复，而非等待全部生成完成',
    scope: 'global',
    storage: 'app_settings',
    defaultValue: true,
    applyMode: 'immediate',
    visibility: 'basic',
    riskLevel: 'low',
    constraints: { type: 'boolean' }
  },
  
  'maxContext': {
    key: 'maxContext',
    label: '上下文窗口',
    description: '单次对话发送给模型的最大 token 数',
    scope: 'global',
    storage: 'app_settings',
    defaultValue: 4096,
    applyMode: 'next-request',
    visibility: 'basic',
    riskLevel: 'medium',
    constraints: { 
      type: 'number', 
      min: 256, 
      max: 128000 
    },
    dependsOn: ['autoContext'],
    validate: (v) => {
      if (typeof v !== 'number' || v < 256) {
        return '上下文窗口不能小于 256 tokens';
      }
      return null;
    }
  },
  
  'maxConcurrentSubagents': {
    key: 'maxConcurrentSubagents',
    label: '最大并发子任务数',
    description: '编排器同时运行的子任务数量',
    scope: 'global',
    storage: 'app_settings',
    storageKey: 'orch.maxConcurrentSubagents',
    defaultValue: 4,
    applyMode: 'next-run',
    visibility: 'advanced',
    riskLevel: 'medium',
    constraints: { 
      type: 'number', 
      min: 1,  // 关键：禁止 0
      max: 100 
    },
    validate: (v) => {
      if (typeof v !== 'number' || v < 1) {
        return '并发数必须大于 0，否则编排器会挂死';
      }
      return null;
    }
  },
  
  // ... 其他设置项
};
```

### 4.3 自动化工具

基于元数据注册表，自动生成：

1. **搜索索引**: `settingsSearchIndex.ts` 从注册表生成
2. **默认值说明**: 每个设置项显示"默认值: xxx"
3. **生效时机标签**: 每个设置项显示"立即生效" / "下次请求" 等
4. **高级设置折叠**: 根据 `visibility` 自动折叠
5. **输入约束**: 自动生成 `min` / `max` / `pattern` 等
6. **契约测试**: 自动验证默认值和约束

## 5. 存储契约统一

### 5.1 现状问题

| 存储 | 用途 | 问题 |
|---|---|---|
| `app_settings` blob | 端点、模型、编排等 | 有 `LEGAL_TOP_KEYS` 白名单，扩展受限 |
| preferences KV | 权限、网络、搜索等 | 无类型约束，JSON 字符串 |
| Electron JSON | 更新配置 | 独立于后端，无 UI 覆盖 |
| localStorage | 主题、字体等 | 前端独享，后端不感知 |

### 5.2 统一方案

**不改变实际存储位置**，但在元数据层统一契约：

1. 每个设置项在元数据中声明 `storage` 和 `storageKey`
2. 前端通过统一的 `settingsClient` 读写，屏蔽底层差异
3. 后端提供 `/api/v1/settings/metadata` 返回所有设置的元数据（可选）
4. 设置页 UI 从元数据生成，不关心存储细节

### 5.3 迁移策略

**Phase 1**: 建立元数据注册表，不改存储  
**Phase 2**: 统一 `settingsClient` 接口，内部路由到不同存储  
**Phase 3**: 后端提供 metadata API（可选）

## 6. 实施计划

### 6.1 Phase 1: 元数据与 P0 修复（1-2 天）

#### 任务 1.1: 建立设置元数据注册表
- 创建 `src/entities/setting/metadata.ts`
- 创建 `src/entities/setting/settingsRegistry.ts`
- 为所有现有设置项定义元数据
- **文件**: 2-3 个新文件

#### 任务 1.2: P0 关键修复
- 修复编排 `maxConcurrentSubagents` 最小值为 1
- 修复 `maxContext` / `autoContext` 交互和说明
- 修复 Temperature 描述
- 修复 Embedding 状态显示
- 修复 GatewayCard 重启提示
- **文件**: 5-6 个现有文件修改

#### 任务 1.3: 生效时机标签
- 创建 `<ApplyModeBadge />` 组件
- 在所有设置项旁显示生效时机
- **文件**: 1 个新组件，5-10 个现有文件修改

#### 任务 1.4: 更新页补齐
- 补齐 6 个缺失的更新配置
- 分为"基础"和"高级折叠"两组
- **文件**: `UpdatesTab.tsx` 重构

#### 任务 1.5: 契约测试
- 为每个设置项的默认值、约束、元数据完整性写测试
- **文件**: 1-2 个测试文件

### 6.2 Phase 2: 信息架构重构（2-3 天）

#### 任务 2.1: 拆分 GeneralTab
- 创建 `BasicTab`（主题/语言/字体/时区/托盘）
- 创建 `MemoryKnowledgeTab`（记忆/嵌入/RAG/话题检测）
- 创建 `ToolsConnectionsTab`（MCP/Hooks/网关/凭据）
- **文件**: 3-4 个新 Tab 文件

#### 任务 2.2: 高级设置折叠
- 创建 `<AdvancedSection />` 组件
- 在 Memory、Orchestration、Updates 等 Tab 中使用
- **文件**: 1 个新组件，5-6 个现有文件修改

#### 任务 2.3: 搜索索引自动化
- 从 `settingsRegistry` 自动生成搜索索引
- 支持结果定位到具体控件
- **文件**: `settingsSearchIndex.ts` 重构

#### 任务 2.4: Settings.tsx 重构
- 从 10+ Tab 收敛为 7 个主类
- 统一 Tab 渲染逻辑
- **文件**: `Settings.tsx` 重构

### 6.3 Phase 3: 存储契约统一（1-2 天）

#### 任务 3.1: settingsClient 统一
- 根据元数据的 `storage` 字段路由到不同存储
- 屏蔽 `app_settings` / preferences / Electron / localStorage 差异
- **文件**: `settingsClient.ts` 重构

#### 任务 3.2: 保存失败反馈
- 统一错误处理
- 显示 Toast 或内联错误
- **文件**: 3-5 个现有文件修改

#### 任务 3.3: 当前有效配置摘要
- 在设置页顶部显示"当前模型/上下文/嵌入器/网络模式/权限模式"
- **文件**: 1 个新组件

### 6.4 Phase 4: 测试与文档（1 天）

#### 任务 4.1: 完整契约测试
- 每个设置项的默认值、约束、元数据完整性
- 存储路由测试
- **文件**: 2-3 个测试文件

#### 任务 4.2: 用户文档更新
- 更新 `docs/user-manual/` 中的设置说明
- **文件**: 1-2 个文档文件

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 元数据定义不完整 | 中 | 中 | 先覆盖 P0 设置项，逐步补全 |
| 存储路由引入 bug | 中 | 高 | Phase 1 不改存储，Phase 3 逐步迁移 |
| 信息架构重构影响现有用户 | 低 | 中 | 保留旧 Tab 的 URL 兼容 |
| 测试覆盖不全 | 中 | 中 | 每个设置项强制写契约测试 |
| 工期超出 | 中 | 中 | Phase 1 优先交付 P0，Phase 2-4 可拆分 |

## 8. 验收标准

### 8.1 功能验收
- [ ] 所有设置项都有明确的生效时机标签
- [ ] 编排 `maxConcurrentSubagents` 不能设为 0
- [ ] `maxContext` / `autoContext` 交互清晰
- [ ] Temperature 描述准确
- [ ] Embedding 状态显示正确（字面/语义/API）
- [ ] GatewayCard 明确提示重启
- [ ] 更新页显示所有 8 个配置
- [ ] 搜索结果可以定位到具体控件

### 8.2 架构验收
- [ ] 设置元数据注册表完整
- [ ] 搜索索引从元数据自动生成
- [ ] 高级设置可折叠
- [ ] 保存失败有明确反馈
- [ ] 通用 Tab 已拆分

### 8.3 测试验收
- [ ] 每个设置项的默认值有测试
- [ ] 每个设置项的约束有测试
- [ ] 存储路由有测试
- [ ] 契约测试覆盖率 > 90%

### 8.4 用户体验验收
- [ ] 基础用户只看基础设置
- [ ] 高级用户可展开高级设置
- [ ] 敏感操作有风险提示
- [ ] 设置页加载时间 < 1s

## 9. 里程碑

| 里程碑 | 时间 | 交付物 |
|---|---|---|
| M1: 元数据注册表 | Day 1 | `metadata.ts` + `settingsRegistry.ts` |
| M2: P0 修复 | Day 1-2 | 编排约束、上下文交互、Temperature、Embedding、Gateway |
| M3: 生效时机标签 | Day 2 | `<ApplyModeBadge />` 组件 |
| M4: 更新页补齐 | Day 2 | 6 个新配置 |
| M5: 契约测试 | Day 2-3 | 默认值、约束、元数据测试 |
| M6: GeneralTab 拆分 | Day 3-4 | Basic/Memory/Tools Tab |
| M7: 高级设置折叠 | Day 4 | `<AdvancedSection />` 组件 |
| M8: 搜索索引自动化 | Day 4-5 | 从元数据生成索引 |
| M9: Settings.tsx 重构 | Day 5 | 7 个主类 |
| M10: settingsClient 统一 | Day 5-6 | 存储路由 |
| M11: 当前有效配置摘要 | Day 6 | 顶部摘要组件 |
| M12: 完整测试覆盖 | Day 6-7 | 契约测试 > 90% |
| M13: 用户文档 | Day 7 | 设置说明文档 |

## 10. 决策记录

| 决策 | 理由 | 替代方案 |
|---|---|---|
| 不改变实际存储位置 | 降低迁移风险 | 统一存储到单一后端 |
| 元数据驱动 UI | 自动化程度高，减少重复代码 | 手动维护每个 Tab |
| 7 个主类而非 10+ Tab | 减少认知负担 | 保留现有 Tab 结构 |
| 中文优先 | 用户反馈优先 | 同步 i18n |
| Phase 1 不改存储 | 先稳定元数据层 | 一开始就统一存储 |

## 11. 附录

### 11.1 现有设置项清单

**app_settings blob**:
- streaming, autoMemory, confirmDelete
- endpoints[], modelSelections{}
- maxContext, autoContext, temperature
- timezone, logTimezone
- wiki{}, orch{}
- demoMode, version

**preferences KV**:
- permission_mode, permission_rules
- network_policy, web_proxy, search_config
- web_access_config, browser_credential_vault
- bash_config, session_model_overrides
- spend_limit_usd, auto_checkpoint, fallback_model
- embedding_mode, context_turn_limit
- auto_topic_detection, topic_detection_threshold
- arena_master_key, hooks
- theme_mode, theme_preset
- font_ui, font_code, font_size_ui, font_size_code
- current_session_id, compact_threshold_tokens

**Electron JSON**:
- updateStrategy, channel
- rollbackWindowDays, autoRollbackThreshold
- checkIntervalHours, updateServerUrl
- enableTelemetry, cacheRetentionDays
- close_to_tray, demoMode

**localStorage**:
- sage:settings-tab
- sage:chat-attachment-rag
- theme, locale

### 11.2 参考产品

- ChatGPT: Memory / Data Controls / Custom Instructions
- Claude: Memory / Capabilities / Connectors / Appearance
- LM Studio: Per-model Defaults / Server Settings / Runtime
- AnythingLLM: System LLM / Workspace LLM / Agent LLM / RAG Settings
- Jan: General / Models / Advanced / Privacy

---

**下一步**: 等待用户审批后，从 Phase 1 任务 1.1 开始实施。
