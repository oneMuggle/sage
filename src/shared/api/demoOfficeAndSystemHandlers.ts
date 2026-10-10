import { asNum, asStr, DEMO_WORKSPACE_PATH, demoUUID, NOW_S } from './demoFixturesCore';
import { DEMO_EVOLUTION_LOGS } from './demoFixturesSessionsAndAgents';
import type { McpServerConfig, McpStatusReport } from './mcpClient';
import type {
  LearnResponse,
  OfficeDeleteResponse,
  OfficeDocUpdateResponse,
  OfficeDocumentSummary,
  OfficeExcelReadResult,
  OfficeExportPdfResult,
  OfficePdfReadResult,
  OfficePptReadResult,
  OfficeTemplateInstantiateResult,
  OfficeTemplateListResponse,
  OfficeTemplateMeta,
  OfficeUpdateOp,
  OfficeUpdatePreviewResult,
  OfficeWordReadResult,
} from './types';

const DEMO_OFFICE_DOCS: OfficeDocumentSummary[] = [
  {
    id: 'of-1',
    workspace_path: DEMO_WORKSPACE_PATH,
    doc_type: 'word',
    original_filename: '文献综述报告-大模型医学应用.docx',
    generated_filename: '文献综述报告-大模型医学应用.docx',
    status: 'parsed',
    created_at: NOW_S - 3600 * 26,
    updated_at: NOW_S - 3600 * 2,
    metadata: { page_count: 6, paragraph_count: 58, table_count: 2, file_size_bytes: 42381 },
    derived_from: null,
    archived_at: null,
  },
  {
    id: 'of-2',
    workspace_path: DEMO_WORKSPACE_PATH,
    doc_type: 'excel',
    original_filename: '文献对比表-23篇核心文献.xlsx',
    generated_filename: '文献对比表-23篇核心文献.xlsx',
    status: 'parsed',
    created_at: NOW_S - 86400,
    updated_at: NOW_S - 3600 * 20,
    metadata: { sheet_count: 2, file_size_bytes: 86528 },
    derived_from: null,
    archived_at: null,
  },
  {
    id: 'of-3',
    workspace_path: DEMO_WORKSPACE_PATH,
    doc_type: 'ppt',
    original_filename: null,
    generated_filename: '产品发布会-0827.pptx',
    status: 'generated',
    created_at: NOW_S - 86400 * 2,
    updated_at: NOW_S - 86400 * 2 + 600,
    metadata: { page_count: 5, file_size_bytes: 2516582 },
    derived_from: null,
    archived_at: null,
  },
  {
    id: 'of-4',
    workspace_path: DEMO_WORKSPACE_PATH,
    doc_type: 'pdf',
    original_filename: '检索策略与纳入排除标准.pdf',
    generated_filename: '检索策略与纳入排除标准.pdf',
    status: 'parsed',
    created_at: NOW_S - 3600 * 8,
    updated_at: NOW_S - 3600 * 8,
    metadata: { page_count: 2, file_size_bytes: 1284500 },
    derived_from: null,
    archived_at: null,
  },
];

const DEMO_WORD_READ: OfficeWordReadResult = {
  summary: DEMO_OFFICE_DOCS[0],
  paragraphs: [
    { style: 'Heading 1', text: '文献综述报告：大模型医学应用进展', level: 1 },
    { style: 'Heading 2', text: '1. 研究背景', level: 2 },
    {
      style: 'Normal',
      text: '近三年，大语言模型在医学领域的应用呈爆发式增长。临床诊断辅助方向近三年 PubMed 收录 48 篇，医学影像分析方法迭代最快。',
      level: 0,
    },
    { style: 'Heading 2', text: '2. 关键发现', level: 2 },
    {
      style: 'Normal',
      text: 'Med-PaLM 2 在 MedQA 基准上中位准确率 86.5%；BiomedCLIP 类对比预训练使医学影像任务较监督基线平均提升 +9.2%。',
      level: 0,
    },
    { style: 'Heading 2', text: '3. 研究空白', level: 2 },
    {
      style: 'Normal',
      text: '低资源语言与长尾病种的评测不足；隐私合规（HIPAA）与幻觉率仍是临床落地最大障碍。',
      level: 0,
    },
    { style: 'Heading 2', text: '4. 结论', level: 2 },
    {
      style: 'Normal',
      text: '临床诊断辅助最成熟，药物研发加速商业化最快（候选分子平均筛选成本下降 37%），隐私与安全方向需持续关注。',
      level: 0,
    },
  ],
  tables: [
    {
      rows: [
        ['方向', '篇数', '代表工作'],
        ['临床诊断辅助', '9', 'Med-PaLM 2'],
        ['医学影像分析', '7', 'BiomedCLIP'],
        ['药物研发加速', '4', 'DrugGPT'],
        ['隐私与安全', '3', 'DP-MedLLM'],
      ],
    },
  ],
  images: 1,
};

const DEMO_EXCEL_READ: OfficeExcelReadResult = {
  summary: DEMO_OFFICE_DOCS[1],
  sheets: [
    {
      name: '核心文献',
      rows: [
        ['序号', '标题', '方向', '方法', '数据集', '结论'],
        [
          '01',
          'Med-PaLM 2',
          '临床诊断辅助',
          '指令微调 + 专家反馈',
          'MedQA / MedMCQA',
          '中位准确率 86.5%',
        ],
        ['02', 'BiomedCLIP', '医学影像分析', '对比预训练', 'PMC-15M', '较监督基线 +9.2%'],
        ['03', 'DrugGPT', '药物研发加速', '分子生成', 'ChEMBL', '筛选成本 -37%'],
        ['04', 'DP-MedLLM', '隐私与安全', '差分隐私微调', 'MIMIC-III', '满足 HIPAA 要求'],
      ],
      max_row: 5,
      max_col: 6,
    },
    {
      name: '年份分布',
      rows: [
        ['年份', '篇数'],
        ['2024', '6'],
        ['2025', '9'],
        ['2026', '8'],
      ],
      max_row: 4,
      max_col: 2,
    },
  ],
};

const DEMO_PPT_READ: OfficePptReadResult = {
  summary: DEMO_OFFICE_DOCS[2],
  slides: [
    {
      index: 1,
      title: 'Sage 0.4.10 产品发布会',
      text_blocks: ['多智能体编排 · 记忆系统 · Office 集成'],
      table_count: 0,
      image_count: 1,
      notes: '开场：介绍本次发布主题',
    },
    {
      index: 2,
      title: '痛点',
      text_blocks: ['重复任务分散注意力', '跨会话上下文丢失'],
      table_count: 0,
      image_count: 0,
      notes: null,
    },
    {
      index: 3,
      title: '解决方案',
      text_blocks: [
        'Planner / Executor / Reviewer 三角色编排',
        '四层记忆自动沉淀',
        'Office 文档读写一体',
      ],
      table_count: 0,
      image_count: 1,
      notes: '展示编排拓扑图',
    },
    {
      index: 4,
      title: '实战场景',
      text_blocks: ['实战场景：文献调研 → 自动生成综述报告'],
      table_count: 1,
      image_count: 0,
      notes: '实战场景走查 3 分钟',
    },
    {
      index: 5,
      title: '路线图',
      text_blocks: ['0.5.0：MCP 生态扩展', '0.6.0：多端同步'],
      table_count: 0,
      image_count: 0,
      notes: null,
    },
  ],
};

const DEMO_PDF_READ: OfficePdfReadResult = {
  summary: DEMO_OFFICE_DOCS[3],
  pages: [
    {
      page_number: 1,
      text: '检索策略与纳入排除标准\n\n数据库：PubMed / Embase / Cochrane Library\n检索时间窗：2023-01 至 2026-06',
      tables: [],
      images: [],
    },
    {
      page_number: 2,
      text: '纳入标准：\n1. 同行评审英文文献\n2. 报告大模型在临床任务上的定量评测\n排除标准：预印本、单案例报告。',
      tables: [],
      images: [],
    },
  ],
  metadata: { producer: 'Sage demo', page_count: 2 },
};

// ─────────────────────────────────────────────────────────────────────────
// 用量统计 / 会话摘要 / 定时任务 / 技能执行输出
// ─────────────────────────────────────────────────────────────────────────


let demoOfficeDocs: OfficeDocumentSummary[] = [...DEMO_OFFICE_DOCS];

const DEMO_OFFICE_TEMPLATES: OfficeTemplateMeta[] = [
  {
    id: 'weekly_report',
    name: '周报模板',
    description: '标准周报：本周进展、数据指标与下周计划。',
    doc_type: 'word',
    placeholders: [
      { name: 'author', type: 'text', description: '作者姓名' },
      { name: 'report_date', type: 'date', description: '报告日期' },
      { name: 'this_week', type: 'rich_text', description: '本周进展' },
      { name: 'metrics_table', type: 'table', description: '关键指标表' },
    ],
    source: 'builtin',
  },
  {
    id: 'meeting_minutes',
    name: '会议纪要模板',
    description: '会议纪要：议题、结论与行动项。',
    doc_type: 'word',
    placeholders: [
      { name: 'title', type: 'text', description: '会议主题' },
      { name: 'attendees', type: 'text', description: '参会人' },
      { name: 'conclusions', type: 'rich_text', description: '会议结论' },
    ],
    source: 'builtin',
  },
  {
    id: 'budget_sheet',
    name: '预算表模板',
    description: '部门预算：填入部门与预算明细表。',
    doc_type: 'excel',
    placeholders: [
      { name: 'department', type: 'text', description: '部门名称' },
      { name: 'budget_table', type: 'table', description: '预算明细' },
    ],
    source: 'builtin',
  },
  {
    id: 'project_review',
    name: '项目评审模板',
    description: '项目评审：项目名、评审日期与结论。',
    doc_type: 'ppt',
    placeholders: [
      { name: 'project', type: 'text', description: '项目名称' },
      { name: 'review_date', type: 'date', description: '评审日期' },
    ],
    source: 'builtin',
  },
];

// Preferences KV (get_preference / set_preference): 后端不在, 用内存 Map 顶替。
// current_session_id 特判返回演示文献调研会话, 首屏直接落到聊天页。

export function createDemoOfficeAndSystemHandlers(): Record<string, (args: Record<string, unknown>) => unknown> {
  return {
  office_list_documents: () => ({ documents: [...demoOfficeDocs], total: demoOfficeDocs.length }),

  office_delete_document: (args) => {
    const docId = asStr(args.docId) || asStr(args.id);
    demoOfficeDocs = demoOfficeDocs.filter((d) => d.id !== docId);
    const result: OfficeDeleteResponse = { id: docId, deleted: true };
    return result;
  },

  office_word_read: () => DEMO_WORD_READ,
  office_excel_read: () => DEMO_EXCEL_READ,
  office_ppt_read: () => DEMO_PPT_READ,
  office_pdf_read: () => DEMO_PDF_READ,
  // F3 (office-p0): demo 模式没有真实 PDF 字节可 base64 化 —— 显式
  // ok:false 让"原文预览"开关走失败回落，而不是未知通道报错。
  office_pdf_data: () => ({ ok: false, data_url: null, error: '演示模式不支持原文预览' }),

  // Round-3 N1: PDF 生成演示路径（生成表单 e2e 的正向用例依赖）
  office_pdf_generate: (args) => {
    const workspacePath =
      asStr(args.workspace_path) || asStr(args.workspacePath) || DEMO_WORKSPACE_PATH;
    const filename = asStr(args.filename) || '文档.pdf';
    const doc: OfficeDocumentSummary = {
      id: demoUUID(),
      workspace_path: workspacePath,
      doc_type: 'pdf',
      original_filename: null,
      generated_filename: filename,
      status: 'generated',
      created_at: NOW_S,
      updated_at: NOW_S,
      metadata: { page_count: 2, file_size_bytes: 88320 },
      derived_from: null,
      archived_at: null,
    };
    demoOfficeDocs = [doc, ...demoOfficeDocs];
    return {
      output_path: `${workspacePath}/${filename}`,
      filename,
      file_size_bytes: 88320,
      page_count: 2,
    };
  },

  // Office parity batch 1 (item 1.7): archive / restore + snapshots.
  office_archive_document: (args) => {
    const docId = asStr(args.docId) || asStr(args.id);
    const doc = demoOfficeDocs.find((d) => d.id === docId);
    const archivedAt = doc?.archived_at ?? NOW_S * 1000;
    if (doc) doc.archived_at = archivedAt;
    return { ok: true, summary: doc ?? null };
  },

  office_restore_document: (args) => {
    const docId = asStr(args.docId) || asStr(args.id);
    const doc = demoOfficeDocs.find((d) => d.id === docId);
    if (doc) doc.archived_at = null;
    return { ok: true, summary: doc ?? null };
  },

  office_list_snapshots: () => ({
    snapshots: [
      {
        snapshot_id: `${(NOW_S - 7200) * 1000}-文献对比表-23篇核心文献.xlsx`,
        size_bytes: 85504,
        created_at: (NOW_S - 7200) * 1000,
      },
      {
        snapshot_id: `${(NOW_S - 3600) * 1000}-文献对比表-23篇核心文献.xlsx`,
        size_bytes: 86528,
        created_at: (NOW_S - 3600) * 1000,
      },
    ],
  }),

  office_restore_snapshot: (args) => {
    const docId = asStr(args.docId);
    const doc = demoOfficeDocs.find((d) => d.id === docId);
    if (doc) doc.updated_at = NOW_S * 1000;
    return { ok: true, summary: doc ?? null };
  },

  office_word_generate: (args) => {
    const workspacePath =
      asStr(args.workspace_path) || asStr(args.workspacePath) || DEMO_WORKSPACE_PATH;
    const filename = asStr(args.filename) || '文档.docx';
    const doc: OfficeDocumentSummary = {
      id: demoUUID(),
      workspace_path: workspacePath,
      doc_type: 'word',
      original_filename: null,
      generated_filename: filename,
      status: 'generated',
      created_at: NOW_S,
      updated_at: NOW_S,
      metadata: { paragraph_count: 12, table_count: 1, file_size_bytes: 24576 },
      derived_from: null,
      archived_at: null,
    };
    demoOfficeDocs = [doc, ...demoOfficeDocs];
    return { output_path: `${workspacePath}/${filename}`, filename, file_size_bytes: 24576 };
  },

  office_excel_generate: (args) => {
    const workspacePath =
      asStr(args.workspace_path) || asStr(args.workspacePath) || DEMO_WORKSPACE_PATH;
    const filename = asStr(args.filename) || '数据表.xlsx';
    const doc: OfficeDocumentSummary = {
      id: demoUUID(),
      workspace_path: workspacePath,
      doc_type: 'excel',
      original_filename: null,
      generated_filename: filename,
      status: 'generated',
      created_at: NOW_S,
      updated_at: NOW_S,
      metadata: { sheet_count: 1, file_size_bytes: 18432 },
      derived_from: null,
      archived_at: null,
    };
    demoOfficeDocs = [doc, ...demoOfficeDocs];
    return { output_path: `${workspacePath}/${filename}`, filename, file_size_bytes: 18432 };
  },

  office_ppt_generate: (args) => {
    const workspacePath =
      asStr(args.workspace_path) || asStr(args.workspacePath) || DEMO_WORKSPACE_PATH;
    const filename = asStr(args.filename) || '幻灯片.pptx';
    const doc: OfficeDocumentSummary = {
      id: demoUUID(),
      workspace_path: workspacePath,
      doc_type: 'ppt',
      original_filename: null,
      generated_filename: filename,
      status: 'generated',
      created_at: NOW_S,
      updated_at: NOW_S,
      metadata: { page_count: 4, file_size_bytes: 1048576 },
      derived_from: null,
      archived_at: null,
    };
    demoOfficeDocs = [doc, ...demoOfficeDocs];
    return { output_path: `${workspacePath}/${filename}`, filename, file_size_bytes: 1048576 };
  },

  // Office parity batch 2 (items 2.5 / 2.7): update preview (dry-run) +
  // PDF export. Preview turns each composed op into one generic change
  // entry (the real backend diffs against a temp copy — demo just echoes
  // a plausible shape so the dialog state machine is exercisable).
  office_update_preview: (args) => {
    const ops = Array.isArray(args.ops) ? (args.ops as OfficeUpdateOp[]) : [];
    const changes = ops.slice(0, 200).map((raw) => {
      const op = typeof raw?.op === 'string' ? raw.op : 'unknown';
      if (op === 'replace_text') {
        return {
          op,
          target: asStr(raw.find),
          before: asStr(raw.find),
          after: asStr(raw.replace),
        };
      }
      if (op === 'set_cells') {
        const sheet = asStr(raw.sheet) || 'Sheet1';
        const cells = Array.isArray(raw.cells) ? raw.cells : [];
        const first = cells[0] as Record<string, unknown> | undefined;
        return {
          op,
          target: first ? `${sheet}!${asStr(first.addr)}` : sheet,
          after: first ? asStr(first.value) : '',
        };
      }
      if (op === 'set_slide_title') {
        return {
          op,
          target: `slide[${asNum(raw.index, 0)}]`,
          after: asStr(raw.title),
        };
      }
      return { op, summary: `${op}` };
    });
    const result: OfficeUpdatePreviewResult = {
      ok: true,
      changes,
      truncated: ops.length > 200,
      error: null,
      // F1: the demo stub carries the version stamp too, so the dialog's
      // preview → apply revision handshake is exercisable without a backend.
      source_revision: `sha256:demo-${asStr(args.docId) || 'doc'}`,
      ops_hash: `ops:demo-${ops.length}`,
      preview_id: `pv_demo_${ops.length}`,
    };
    return result;
  },

  office_export_pdf: (args) => {
    const filePath = asStr(args.filePath) || asStr(args.file_path) || 'document.docx';
    const outputPath = filePath.replace(/\.(docx|xlsx|pptx)$/i, '.pdf');
    const result: OfficeExportPdfResult = {
      ok: true,
      method: 'libreoffice',
      output_path: outputPath,
      error: null,
    };
    return result;
  },

  // Office parity round 2 (R1): 页内应用编辑 —— 回读 preview 的 ops 真正
  // 写入 demo 文档行 (status → edited, updated_at 刷新), 并按后端契约回
  // {ok, summary, self_check}。self_check.summary 模拟后端自检回读的
  // 计数形状。未知 doc 在 demo 里不抛 404 (与 archive/restore 桩一致)。
  office_doc_update: (args) => {
    const docId = asStr(args.docId);
    const doc = demoOfficeDocs.find((d) => d.id === docId);
    const ops = Array.isArray(args.ops) ? (args.ops as OfficeUpdateOp[]) : [];
    if (doc) {
      doc.status = 'edited';
      doc.updated_at = NOW_S * 1000;
    }
    const result: OfficeDocUpdateResponse = {
      ok: true,
      summary: doc ?? demoOfficeDocs[0],
      self_check: {
        ok: true,
        summary: { ops_applied: ops.length, re_read: true },
        error: null,
      },
      previous_revision: asStr(args.expectedRevision) || null,
      revision: `sha256:demo-${docId || 'doc'}-${ops.length}`,
      idempotent_replay: false,
    };
    return result;
  },

  // F1/F2: content revision probe (GET /office/doc/{id}/revision). The demo
  // derives a stable pseudo-hash from the row so the preview cache key
  // changes exactly when the demo document does.
  office_doc_revision: (args) => {
    const docId = asStr(args.docId);
    const doc = demoOfficeDocs.find((d) => d.id === docId);
    return {
      doc_id: docId,
      revision: `sha256:demo-${docId}-${doc?.updated_at ?? 0}`,
      size_bytes: doc?.metadata?.file_size_bytes ?? 0,
      mtime_ms: doc?.updated_at ?? 0,
    };
  },

  // Office parity batch 3 (item 3.2): 模板库 — 列表返回内置模板 (round-3
  // N2 起覆盖 word/excel/ppt); instantiate 走 office_*_generate 同款入库桩
  // (新文档出现在文档列表, doc_type 按扩展名推断), 并按 fill-template 结果
  // 形状回填 filled_count / unfilled_placeholders。
  office_list_templates: (): OfficeTemplateListResponse => ({
    templates: DEMO_OFFICE_TEMPLATES,
  }),

  office_templates_instantiate: (args) => {
    const workspacePath =
      asStr(args.workspacePath) || asStr(args.workspace_path) || DEMO_WORKSPACE_PATH;
    const filename = asStr(args.filename) || '模板文档.docx';
    const data = (args.data as Record<string, string>) ?? {};
    // Round-3 N2: the backend picks the filler by the template's
    // doc_type — the demo stub infers it from the output extension.
    const docType: OfficeDocumentSummary['doc_type'] = filename.toLowerCase().endsWith('.xlsx')
      ? 'excel'
      : filename.toLowerCase().endsWith('.pptx')
        ? 'ppt'
        : 'word';
    const metadata: OfficeDocumentSummary['metadata'] =
      docType === 'excel'
        ? { sheet_count: 1, file_size_bytes: 12000 }
        : docType === 'ppt'
          ? { page_count: 1, file_size_bytes: 30000 }
          : { paragraph_count: 8, table_count: 0, file_size_bytes: 21504 };
    const doc: OfficeDocumentSummary = {
      id: demoUUID(),
      workspace_path: workspacePath,
      doc_type: docType,
      original_filename: null,
      generated_filename: filename,
      status: 'generated',
      created_at: NOW_S,
      updated_at: NOW_S,
      metadata,
      derived_from: null,
      archived_at: null,
    };
    demoOfficeDocs = [doc, ...demoOfficeDocs];
    const filledCount = Object.values(data).filter((v) => String(v).trim() !== '').length;
    const result: OfficeTemplateInstantiateResult = {
      output_path: `${workspacePath}/${filename}`,
      filename,
      file_size_bytes: metadata.file_size_bytes,
      filled_count: filledCount,
      unfilled_placeholders: [],
    };
    return result;
  },

  // ── 进化 / 学习 ──
  trigger_learn: () => {
    const response: LearnResponse = { status: 'queued', message: '已加入后台审阅队列' };
    return response;
  },

  get_evolution_logs: (args) => {
    const offset = Math.max(0, asNum(args.offset, 0));
    const limit = Math.min(100, Math.max(1, asNum(args.limit, 20)));
    return DEMO_EVOLUTION_LOGS.slice(offset, offset + limit);
  },

  // ── MCP ──
  mcp_status: () => {
    const report: McpStatusReport = {
      generated_at: NOW_S,
      all_ready: true,
      degraded: false,
      failed_required: false,
      servers: [
        {
          name: 'filesystem',
          state: 'ready',
          tool_count: 6,
          last_error: null,
          since: NOW_S - 3600,
          required: false,
        },
      ],
    };
    return report;
  },

  mcp_servers: () => {
    const config: McpServerConfig = {
      name: 'filesystem',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-filesystem', DEMO_WORKSPACE_PATH],
      env: {},
      enabled: true,
      required: false,
      timeout_seconds: 30,
      builtin: false,
    };
    return { servers: [config] };
  },

  mcp_server_add: (args) => {
    const config: McpServerConfig = {
      name: asStr(args.name),
      command: asStr(args.command),
      args: Array.isArray(args.args)
        ? (args.args.filter((a) => typeof a === 'string') as string[])
        : [],
      env: {},
      enabled: true,
      required: args.required === true,
      timeout_seconds: 30,
      builtin: false,
    };
    return config;
  },

  mcp_server_update: (args) => {
    const config: McpServerConfig = {
      name: asStr(args.name),
      command: asStr(args.command),
      args: Array.isArray(args.args)
        ? (args.args.filter((a) => typeof a === 'string') as string[])
        : [],
      env: {},
      enabled: args.enabled !== false,
      required: args.required === true,
      timeout_seconds: 30,
      builtin: false,
    };
    return config;
  },

  mcp_server_delete: () => ({ ok: true }),

  // ── 主题 ──
  theme_list: () => [],
  theme_get: () => null,
  theme_save: (args) => ({ id: demoUUID(), ...args }),
  theme_delete: () => ({ ok: true }),

  // ── 流控制 ──
  interrupt_agent: () => ({ ok: true }),
  questions_answer: () => ({ ok: true }),
  permissions_answer: () => ({ ok: true }),
};

}
