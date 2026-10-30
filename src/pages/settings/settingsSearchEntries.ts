/**
 * 设置项搜索索引条目表。
 *
 * 自 `settingsSearchIndex.ts` 拆出，以满足单文件 800 行质量门禁；
 * 查询/格式化/治理函数仍在 `settingsSearchIndex.ts`，对外 API 不变。
 */

import type { SettingsTabKey } from './settingsTabs';

export interface SettingsSearchEntry {
  /** 条目稳定标识 */
  key: string;
  /** 所属 tab */
  tab: SettingsTabKey;
  /** 展示名 (中文，与控件 label 一致) */
  label: string;
  /** 展示名 (英文) */
  labelEn: string;
  /** 小写关键词，含中英别名与 setting key 本身 */
  keywords: string;
}

export const SETTINGS_SEARCH_INDEX: SettingsSearchEntry[] = [
  // ── 通用 ──
  {
    key: 'theme',
    tab: 'basic',
    label: '主题',
    labelEn: 'Theme',
    keywords: 'theme 主题 深色 浅色 dark light 外观',
  },
  {
    key: 'locale',
    tab: 'basic',
    label: '界面语言',
    labelEn: 'Language',
    keywords: 'locale language 语言 中文 english',
  },
  {
    key: 'font_ui',
    tab: 'basic',
    label: '界面字体',
    labelEn: 'UI font',
    keywords: 'font 字体 ui interface 外观',
  },
  {
    key: 'font_size_ui',
    tab: 'basic',
    label: '界面字号',
    labelEn: 'UI font size',
    keywords: 'font size 字号 字体大小',
  },
  {
    key: 'font_code',
    tab: 'basic',
    label: '代码字体',
    labelEn: 'Code font',
    keywords: 'code font 代码字体 等宽 mono',
  },
  {
    key: 'font_size_code',
    tab: 'basic',
    label: '代码字号',
    labelEn: 'Code font size',
    keywords: 'code font size 代码字号',
  },
  {
    key: 'streaming',
    tab: 'basic',
    label: '流式输出',
    labelEn: 'Streaming',
    keywords: 'streaming 流式 逐字 输出',
  },
  {
    key: 'inputHistorySize',
    tab: 'basic',
    label: '输入历史条数',
    labelEn: 'Input history size',
    keywords: 'input history size 输入 历史 条数 上限',
  },
  {
    key: 'llmRetryMaxAttempts',
    tab: 'basic',
    label: '最大重试次数',
    labelEn: 'Max retry attempts',
    keywords: 'llm retry max attempts 重试 次数 最大 自动重试',
  },
  {
    key: 'llmRetryBaseDelayS',
    tab: 'basic',
    label: '退避基数（秒）',
    labelEn: 'Retry base delay (s)',
    keywords: 'llm retry base delay 退避 基数 秒 指数退避',
  },
  {
    key: 'llmRetryMaxDelayS',
    tab: 'basic',
    label: '最大退避（秒）',
    labelEn: 'Max retry delay (s)',
    keywords: 'llm retry max delay 最大 退避 上限 秒',
  },
  {
    key: 'llmTotalTimeoutS',
    tab: 'basic',
    label: '整轮任务总耗时上限（秒）',
    labelEn: 'Total task time limit (s)',
    keywords: 'llmtotaltimeouts llm total timeout 整轮 任务 总耗时 上限 超时 秒 不限',
  },
  {
    key: 'llmProxyTimeoutS',
    tab: 'basic',
    label: 'LLM 代理超时（秒）',
    labelEn: 'LLM proxy timeout (s)',
    keywords: 'llmproxytimeouts proxy timeout 代理 超时 秒 卡住 不出字 网关 慢',
  },
  {
    key: 'timezone',
    tab: 'basic',
    label: 'IANA 时区',
    labelEn: 'Timezone',
    keywords: 'timezone 时区 iana asia/shanghai',
  },
  {
    key: 'logTimezone',
    tab: 'basic',
    label: '日志时区',
    labelEn: 'Log timezone',
    keywords: 'log timezone 日志时区 utc',
  },
  {
    key: 'autoMemory',
    tab: 'memory',
    label: '自动记忆提取',
    labelEn: 'Auto memory extraction',
    keywords: 'automemory 记忆 自动提取',
  },
  {
    key: 'confirmDelete',
    tab: 'memory',
    label: '确认后再删除记忆',
    labelEn: 'Confirm before deleting memory',
    keywords: 'confirmdelete 删除记忆 确认',
  },
  {
    key: 'context_turn_limit',
    tab: 'memory',
    label: '上下文轮数限制',
    labelEn: 'Context turn limit',
    keywords: 'context turn limit 上下文 轮数 隔离 不限',
  },
  {
    key: 'attachment_rag',
    tab: 'basic',
    label: '超长文档检索注入',
    labelEn: 'Attachment RAG',
    keywords: 'rag 附件 检索 embedding 长文档 top_k',
  },
  {
    key: 'auto_checkpoint',
    tab: 'memory',
    label: '发送前自动快照',
    labelEn: 'Auto checkpoint',
    keywords: 'checkpoint 快照 安全网 回滚 撤销',
  },
  {
    key: 'close_to_tray',
    tab: 'basic',
    label: '关闭时隐藏到托盘',
    labelEn: 'Close to tray',
    keywords: 'tray 托盘 关闭 最小化',
  },
  {
    key: 'demoMode',
    tab: 'basic',
    label: '演示模式',
    labelEn: 'Demo mode',
    keywords: 'demo 演示 示例数据 离线',
  },
  {
    key: 'permission_mode',
    tab: 'tools-connections',
    label: '权限模式',
    labelEn: 'Permission mode',
    keywords: 'permission 权限 只读 full_access workspace_write 审批',
  },
  {
    key: 'fallback_model',
    tab: 'tools-connections',
    label: '降级模型 (fallback)',
    labelEn: 'Fallback model',
    keywords: 'fallback 降级模型 限流 重试',
  },
  {
    key: 'hooks',
    tab: 'tools-connections',
    label: '钩子 (Hooks)',
    labelEn: 'Hooks',
    keywords: 'hooks 钩子 pre_tool_use 命令',
  },
  {
    key: 'trust_escalation',
    tab: 'tools-connections',
    label: '渐进式授权',
    labelEn: 'Progressive delegation',
    keywords: 'trust 信任 渐进式授权 连续批准 自动放行 progressive delegation threshold',
  },
  {
    key: 'spend_limit',
    tab: 'memory',
    label: '每日花费限额',
    labelEn: 'Daily spend limit',
    keywords: 'spend limit 花费 限额 usd 预算',
  },
  {
    key: 'usage',
    tab: 'basic',
    label: '用量统计',
    labelEn: 'Usage',
    keywords: 'usage 用量 token 统计 导出',
  },
  {
    key: 'diagnostics',
    tab: 'basic',
    label: '诊断与日志级别',
    labelEn: 'Diagnostics',
    keywords: 'diagnostics 诊断 日志级别 log level',
  },
  {
    key: 'gateway',
    tab: 'tools-connections',
    label: '消息网关 (Telegram/Discord/Slack)',
    labelEn: 'Chat gateways',
    keywords: 'gateway telegram discord slack 网关 绑定',
  },
  {
    key: 'reset',
    tab: 'basic',
    label: '恢复默认设置',
    labelEn: 'Reset settings',
    keywords: 'reset 恢复默认 重置 数据',
  },

  // ── 端点 ──
  {
    key: 'endpoints',
    tab: 'models-services',
    label: '端点管理',
    labelEn: 'Endpoints',
    keywords: 'endpoint base url api key 端点 协议 模型探测',
  },

  // ── 模型 ──
  {
    key: 'model_selections',
    tab: 'models-services',
    label: '模型选择',
    labelEn: 'Model selection',
    keywords: 'model chat vision embedding tts asr image 模型选择',
  },
  {
    key: 'title_model',
    tab: 'models-services',
    label: '会话标题模型',
    labelEn: 'Session title model',
    keywords: 'titlemodelid 标题 会话标题 专用模型 title session name',
  },
  {
    key: 'max_context',
    tab: 'models-services',
    label: '最大上下文长度',
    labelEn: 'Max context',
    keywords: 'maxcontext 上下文 context window 长度',
  },
  {
    key: 'auto_context',
    tab: 'models-services',
    label: '自动推断上下文窗口',
    labelEn: 'Auto context',
    keywords: 'autocontext 上下文 自动推断 catalog',
  },
  {
    key: 'max_output_tokens',
    tab: 'models-services',
    label: '最大输出长度',
    labelEn: 'Max output tokens',
    keywords: 'maxoutputtokens 输出 output 长度 截断 token max_tokens',
  },
  {
    key: 'temperature',
    tab: 'models-services',
    label: 'Temperature',
    labelEn: 'Temperature',
    keywords: 'temperature 温度 随机性 采样',
  },
  {
    key: 'model_catalog',
    tab: 'models-services',
    label: '模型目录管理',
    labelEn: 'Model catalog',
    keywords: 'catalog 模型目录 管理',
  },
  // Task 9 (2026-10-28) 智能路由模式 —— Task 11 (ModelsTab) 实际控件在此 Tab。
  {
    key: 'routing.mode',
    tab: 'models-services',
    label: '智能模型路由',
    labelEn: 'Smart model routing',
    keywords: 'routing 智能路由 模型 自动 task_type 按任务选 model auto manual',
  },

  // ── 编排 ──
  {
    key: 'orch.planPreflightEnabled',
    tab: 'orchestration',
    label: '拆解前澄清需求',
    labelEn: 'Pre-plan clarification',
    keywords: 'orch 编排 澄清 提问 计划前置 planpreflightenabled',
  },
  {
    key: 'orch.planScoutEnabled',
    tab: 'orchestration',
    label: '拆解前事实侦察',
    labelEn: 'Pre-plan scout',
    keywords: 'orch 编排 侦察 事实 计划前置 planscoutenabled',
  },
  {
    key: 'orch.maxIterations',
    tab: 'orchestration',
    label: 'Agent 迭代次数上限',
    labelEn: 'Agent iterations limit',
    keywords: 'orch 编排 agent 迭代 上限 maxiterations',
  },
  {
    key: 'orch.maxConcurrentSubagents',
    tab: 'orchestration',
    label: '最大并发子任务数',
    labelEn: 'Max concurrent subagents',
    keywords: 'orch 编排 并发 子任务 maxconcurrentsubagents',
  },
  {
    key: 'orch.maxRetries',
    tab: 'orchestration',
    label: '子任务重试次数',
    labelEn: 'Subtask retries',
    keywords: 'orch 编排 重试 maxretries',
  },
  {
    key: 'orch.maxLaneIterations',
    tab: 'orchestration',
    label: 'Lane 迭代上限',
    labelEn: 'Lane iterations',
    keywords: 'orch 编排 lane 迭代 maxlaneiterations',
  },
  {
    key: 'orch.maxSubagentIterations',
    tab: 'orchestration',
    label: '子代理迭代上限',
    labelEn: 'Subagent iterations',
    keywords: 'orch 编排 子代理 迭代 maxsubagentiterations',
  },
  {
    key: 'orch.maxAggregateChars',
    tab: 'orchestration',
    label: '聚合结果上限',
    labelEn: 'Max aggregate chars',
    keywords: 'orch 编排 聚合 字符 maxaggregatechars',
  },
  {
    key: 'orch.maxSubagentResultChars',
    tab: 'orchestration',
    label: '单结果截断上限',
    labelEn: 'Max subagent result chars',
    keywords: 'orch 编排 截断 字符 maxsubagentresultchars',
  },
  {
    key: 'orch.maxToolCallsPerRun',
    tab: 'orchestration',
    label: '工具调用预算',
    labelEn: 'Tool calls per run',
    keywords: 'orch 编排 工具 调用 预算 maxtoolcallsperrun',
  },
  {
    key: 'orch.runTokenBudget',
    tab: 'orchestration',
    label: 'Run token 预算',
    labelEn: 'Run token budget',
    keywords: 'orch 编排 token 预算 runtokenbudget',
  },
  {
    key: 'orch.runWallClockLimitMinutes',
    tab: 'orchestration',
    label: 'Run 墙钟上限',
    labelEn: 'Run wall-clock limit',
    keywords: 'orch 编排 墙钟 超时 runwallclocklimitminutes',
  },
  {
    key: 'orch.subagentTaskTimeoutS',
    tab: 'orchestration',
    label: '单子任务超时',
    labelEn: 'Subagent task timeout',
    keywords: 'orch 编排 子任务 超时 subagenttasktimeouts',
  },
  {
    key: 'orch.maxRetryOfChains',
    tab: 'orchestration',
    label: '重派链上限',
    labelEn: 'Retry chain limit',
    keywords: 'orch 编排 重派 retry_of maxretryofchains',
  },
  {
    key: 'orch.subagentApprovalMode',
    tab: 'orchestration',
    label: '子代理自动批准',
    labelEn: 'Subagent auto approval',
    keywords: 'orch 编排 审批 自动批准 subagentapprovalmode',
  },
  {
    key: 'orch.worktreeIsolation',
    tab: 'orchestration',
    label: '子任务 git worktree 隔离',
    labelEn: 'Worktree isolation',
    keywords: 'orch 编排 worktree 隔离 git worktreeisolation',
  },
  {
    key: 'orch.scratchRoot',
    tab: 'orchestration',
    label: 'Scratch 根目录名',
    labelEn: 'Scratch root',
    keywords: 'orch 编排 scratch 目录 scratchroot',
  },
  {
    key: 'orch.maxConsecutiveUnansweredQuestions',
    tab: 'orchestration',
    label: '连续未应答提问上限',
    labelEn: 'Max consecutive unanswered questions',
    keywords:
      'orch 编排 提问 澄清 未应答 上限 骚扰 ask_user_question maxconsecutiveunansweredquestions',
  },
  {
    key: 'orch.minOptionsPerQuestion',
    tab: 'orchestration',
    label: '每题最少选项数',
    labelEn: 'Min options per question',
    keywords: 'orch 编排 提问 选项 最少 minoptionsperquestion',
  },
  {
    key: 'orch.maxOptionsPerQuestion',
    tab: 'orchestration',
    label: '每题最多选项数',
    labelEn: 'Max options per question',
    keywords: 'orch 编排 提问 选项 最多 maxoptionsperquestion',
  },
  {
    key: 'orch.maxClarifyQuestionsInPrompt',
    tab: 'orchestration',
    label: '提示词中澄清问题数引导',
    labelEn: 'Max clarify questions in prompt',
    keywords: 'orch 编排 提示词 澄清 问题数 引导 maxclarifyquestionsinprompt',
  },
  {
    key: 'orch.maxClarifyQuestionsPerRound',
    tab: 'orchestration',
    label: '计划前置每轮澄清提问数',
    labelEn: 'Max clarify questions per round',
    keywords: 'orch 编排 计划前置 澄清 每轮 maxclarifyquestionsperround',
  },

  // ── 记忆 ──
  {
    key: 'memory_embedding',
    tab: 'memory',
    label: '语义嵌入',
    labelEn: 'Semantic embedding',
    keywords: 'embedding 语义 嵌入 onnx hash 记忆',
  },
  {
    key: 'memory_consolidation',
    tab: 'memory',
    label: '记忆固化',
    labelEn: 'Memory consolidation',
    keywords: 'consolidation 固化 晋升 衰减 记忆',
  },
  {
    key: 'memory_backup',
    tab: 'memory',
    label: '备份 / 导出 / 导入 / 恢复',
    labelEn: 'Backup & restore',
    keywords: 'backup export import restore 备份 导出 导入 恢复 数据安全',
  },

  // ── 网络 ──
  {
    key: 'remote_workspaces',
    tab: 'remote-workspaces',
    label: '远程工作区（MCP）',
    labelEn: 'Remote workspaces (MCP)',
    keywords: 'remote workspace mcp 远程 工作区 隧道 tunnel cloudflare 急停 emergency 共享 share',
  },
  {
    key: 'network_policy',
    tab: 'network',
    label: '网络模式',
    labelEn: 'Network mode',
    keywords: 'network 网络 模式 内网 气隙 offline intranet online',
  },
  {
    key: 'allowed_hosts',
    tab: 'network',
    label: '主机白名单',
    labelEn: 'Allowed hosts',
    keywords: 'whitelist 白名单 主机 allowed_hosts',
  },
  {
    key: 'insecure_tls',
    tab: 'network',
    label: '跳过 TLS 校验的主机',
    labelEn: 'Insecure TLS hosts',
    keywords: 'tls 证书 自签 insecure',
  },
  {
    key: 'web_proxy',
    tab: 'network',
    label: '抓取代理',
    labelEn: 'Web proxy',
    keywords: 'proxy 代理 http https web_proxy',
  },
  {
    key: 'search_config',
    tab: 'network',
    label: '搜索引擎',
    labelEn: 'Search engines',
    keywords: 'search 搜索 bing ddg tavily zhipu 智谱',
  },
  {
    key: 'web_credentials',
    tab: 'network',
    label: '网站凭据',
    labelEn: 'Site credentials',
    keywords: 'credential 凭据 cookie 登录 header 浏览器',
  },

  // ── MCP ──
  {
    key: 'mcp',
    tab: 'mcp',
    label: 'MCP 服务器',
    labelEn: 'MCP servers',
    keywords: 'mcp server stdio sse oauth 工具 服务器',
  },

  // ── 插件 ──
  {
    key: 'plugins',
    tab: 'plugins-skills',
    label: '插件生命周期',
    labelEn: 'Plugin lifecycle',
    keywords: 'plugin plugins manifest 插件 安装 权限 生命周期 日志',
  },

  // ── Zotero ──
  {
    key: 'zotero',
    tab: 'zotero',
    label: 'Zotero 文献库',
    labelEn: 'Zotero Library',
    keywords: 'zotero 文献 参考文献 library 文献库 引用 cite',
  },

  // ── 开发环境 ──
  {
    key: 'runtime',
    tab: 'runtime',
    label: '运行时探测与诊断',
    labelEn: 'Runtime probes',
    keywords: 'runtime python node 探测 诊断 试跑 开发环境',
  },

  // ── 进化 ──
  {
    key: 'evolution',
    tab: 'evolution',
    label: '进化面板与日志',
    labelEn: 'Evolution',
    keywords: 'evolution 进化 日志',
  },

  // ── Harness ──
  {
    key: 'harness',
    tab: 'harness',
    label: 'Harness 评估面板',
    labelEn: 'Harness dashboard',
    keywords: 'harness 评估 面板 测试 实验 dashboard',
  },

  // ── 更新 ──
  {
    key: 'updates',
    tab: 'updates',
    label: '更新策略与通道',
    labelEn: 'Updates',
    keywords: 'update 更新 策略 通道 stable beta 检查更新',
  },
  {
    key: 'updates.rollbackWindowDays',
    tab: 'updates',
    label: '回滚窗口天数',
    labelEn: 'Rollback window',
    keywords: 'updates.rollbackwindowdays rollback 回滚 窗口 天数 window',
  },
  {
    key: 'updates.autoRollbackThreshold',
    tab: 'updates',
    label: '自动回滚触发次数',
    labelEn: 'Auto rollback threshold',
    keywords: 'updates.autorollbackthreshold rollback 自动回滚 阈值 次数 threshold',
  },
  {
    key: 'updates.checkIntervalHours',
    tab: 'updates',
    label: '自动检查周期',
    labelEn: 'Check interval',
    keywords: 'updates.checkintervalhours 检查周期 interval 小时 hours',
  },
  {
    key: 'updates.updateServerUrl',
    tab: 'updates',
    label: '更新服务器地址',
    labelEn: 'Update server URL',
    keywords: 'updates.updateserverurl 服务器 地址 server url https',
  },
  {
    key: 'updates.enableTelemetry',
    tab: 'updates',
    label: '启用更新遥测',
    labelEn: 'Update telemetry',
    keywords: 'updates.enabletelemetry 遥测 telemetry 上报',
  },
  {
    key: 'updates.cacheRetentionDays',
    tab: 'updates',
    label: '缓存保留天数',
    labelEn: 'Cache retention',
    keywords: 'updates.cacheretentiondays 缓存 cache 保留 天数 retention',
  },
  {
    key: 'providers',
    tab: 'models-services',
    label: '更新源管理',
    labelEn: 'Update sources',
    keywords: 'provider 更新源 镜像 源管理',
  },

  // ── 使用统计 ──
  {
    key: 'usage-stats-summary',
    tab: 'usage-stats',
    label: '用量概览',
    labelEn: 'Usage overview',
    keywords: 'usage stats 用量 统计 token 请求 成本 overview',
  },
  {
    key: 'usage-stats-trend',
    tab: 'usage-stats',
    label: '消耗趋势图',
    labelEn: 'Usage trend chart',
    keywords: 'trend 趋势 折线图 消耗 chart',
  },
  {
    key: 'usage-stats-model',
    tab: 'usage-stats',
    label: '按模型分布',
    labelEn: 'By model',
    keywords: 'model 模型 分布 占比',
  },
  {
    key: 'usage-stats-export',
    tab: 'usage-stats',
    label: '导出 CSV',
    labelEn: 'Export CSV',
    keywords: 'export csv 导出 下载',
  },
  // P0-5: 「通用」tab 此前无任何索引条目 → 搜「重置」无结果，而
  // 「重置全部设置」是破坏性操作，检索不到尤其危险。其余通用 tab 项
  // （权限/降级/消费上限/自动快照/托盘）索引中已存在，无需重复登记。
  {
    key: 'reset_settings',
    tab: 'basic',
    label: '重置全部设置',
    labelEn: 'Reset all settings',
    keywords: 'reset 重置 恢复默认 清除配置 clear defaults',
  },

  // ── 技能 (T-3/T-4) ──
  {
    key: 'skills',
    tab: 'plugins-skills',
    label: '技能',
    labelEn: 'Skills',
    keywords: 'skill 技能 skill.md 脚本 目录',
  },
  {
    key: 'allow_skill_scripts',
    tab: 'plugins-skills',
    label: '允许执行技能脚本',
    labelEn: 'Allow skill script execution',
    keywords: 'allow_skill_scripts 技能 脚本 执行 开关 bash powershell',
  },
  {
    key: 'skills_dir',
    tab: 'plugins-skills',
    label: '技能目录',
    labelEn: 'Skills directory',
    keywords: 'skills_dir 技能 目录 路径 skill.md',
  },

  // ── 全局规则 (G1 / 2026-10-27) ──
  {
    key: 'global_rules',
    tab: 'global-rules',
    label: '全局规则',
    labelEn: 'Global rules',
    keywords: 'global_rules 全局规则 sage.md 系统提示 system prompt',
  },
  {
    key: 'global_rules_editor',
    tab: 'global-rules',
    label: '全局规则编辑器',
    labelEn: 'Global rules editor',
    keywords: 'global_rules_editor 编辑 规则 内容',
  },
  {
    key: 'global_rules_templates',
    tab: 'global-rules',
    label: '全局规则模板',
    labelEn: 'Global rules templates',
    keywords: 'global_rules_templates 模板 套用 中文 安全',
  },
  // ── 用户反馈 (Feedback Hub / 2026-10-29) ──
  {
    key: 'feedback_manager_url',
    tab: 'feedback',
    label: '管理员转发地址',
    labelEn: 'Admin forwarding URL',
    keywords: 'feedback_manager_url 管理员 转发 地址 url 反馈 feedback admin forwarding',
  },
  {
    key: 'feedback_shared_secret',
    tab: 'feedback',
    label: '共享密钥',
    labelEn: 'Shared secret',
    keywords: 'feedback_shared_secret 共享 密钥 secret 鉴权 反馈 feedback auth',
  },
  {
    key: 'feedback_installation_uuid',
    tab: 'feedback',
    label: '本机 ID',
    labelEn: 'Installation ID',
    keywords: 'feedback_installation_uuid 本机 id 安装 uuid 客户端标识 反馈 feedback installation',
  },
  {
    key: 'feedback_sync_now',
    tab: 'feedback',
    label: '立即同步',
    labelEn: 'Sync now',
    keywords: 'feedback_sync_now 立即 同步 反馈 feedback sync',
  },
  {
    key: 'feedback_include_diagnostics',
    tab: 'feedback',
    label: '自动附带诊断日志',
    labelEn: 'Attach diagnostics automatically',
    keywords:
      'feedback_include_diagnostics 诊断 日志 自动 附带 diagnostics log attach 反馈 feedback',
  },
  // ── 诊断与实验 ──
  {
    key: 'audit-export',
    tab: 'audit-export',
    label: '审计导出',
    labelEn: 'Audit export',
    keywords: 'audit export 审计 导出 复制 摘要 json 诊断',
  },
];
