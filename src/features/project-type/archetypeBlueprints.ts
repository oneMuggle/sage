/**
 * 多项目形态组织蓝图与元数据（代码工程 / 一般档案 / 科研项目 / 个人空间，2026-10-10）
 *
 * 与后端 `backend/services/project_archetype_scaffold.py` 及 `backend/data/project_constraint_repo.py`
 * 保持一致，供项目创建向导、侧边栏概览面板、约束管理器与 `/projects` 多态工作台复用。
 */

import type { ProjectType } from '../../shared/api';

export interface ArchetypeStageMeta {
  id: string;
  label: string;
  hint: string;
}

export interface ArchetypeTemplateMeta {
  key: string;
  label: string;
  description: string;
}

export interface ArchetypeBlueprintMeta {
  type: ProjectType;
  label: string;
  englishLabel: string;
  positioning: string;
  defaultVcsMode: 'git' | 'builtin';
  vcsLabel: string;
  directories: string[];
  stages: ArchetypeStageMeta[];
  contextPillars: string[];
  subTemplates: ArchetypeTemplateMeta[];
  sageMdHint: string;
}

export const ARCHETYPE_BLUEPRINTS: Record<ProjectType, ArchetypeBlueprintMeta> = {
  coding: {
    type: 'coding',
    label: '代码工程项目',
    englishLabel: 'Repo-Native & Rule-Triggered',
    positioning: '面向软件研发与工程仓库，提供 Git 分支/Diff 感知、按路径 Glob 触发的编码规范与架构边界护栏。',
    defaultVcsMode: 'git',
    vcsLabel: 'Git 完整分支 / Diff 变更护栏',
    directories: ['src', 'tests', 'docs'],
    stages: [
      { id: 'planning', label: '规划设计', hint: '架构边界、接口契约与技术选型' },
      { id: 'development', label: '研发实现', hint: '核心模块编码、静态检查与重构' },
      { id: 'testing', label: '测试验证', hint: '单测覆盖、集成回归与门禁核验' },
      { id: 'deployment', label: '发布部署', hint: '构建打包、版本发布与变更日志' },
      { id: 'maintenance', label: '持续维护', hint: '线上诊断、性能优化与技术债治理' },
    ],
    contextPillars: [
      'SAGE.md：构建/测试命令、模块分层边界与代码禁区',
      '路径触发约束：*.py / src/**/*.tsx 按活动文件动态注入',
      '运行态感知：Git 分支状态、脏文件数与最近提交历史',
      '架构画像沉淀：自动提取 ADR 架构决策与工程约定',
    ],
    subTemplates: [
      { key: 'python_default', label: 'Python 工程规范', description: 'PEP 8、单函数行数上限与单元测试门禁' },
      { key: 'typescript_react', label: 'TS/React 规范', description: '禁裸 any、显式 Props 接口与语义化 Token' },
      { key: 'security_basic', label: '安全红线基线', description: '禁硬编码密钥、参数化查询与输入校验' },
    ],
    sageMdHint: '自动生成包含构建命令、分层架构契约与研发红线的 SAGE.md。',
  },
  business: {
    type: 'business',
    label: '一般档案与文书',
    englishLabel: 'Dossier-Centric & Template-Governed',
    positioning: '面向公文、合同、招投标与行政企划案卷，采用四级标准立卷目录、免 Git 内置快照与版式/保密合规约束。',
    defaultVcsMode: 'builtin',
    vcsLabel: '内置轻量快照时间线（免安装 Git）',
    directories: [
      '00_立项与背景材料',
      '01_原始依据与佐证',
      '02_编制中工作稿',
      '03_定稿与签发归档',
    ],
    stages: [
      { id: 'initiation', label: '立卷归集', hint: '背景文件、政策依据与原始佐证入卷' },
      { id: 'execution', label: '文书编制', hint: 'Word/Excel/PPT 工作稿协同起草与排版' },
      { id: 'closure', label: '签发封卷', hint: '合规审校、金额术语核验与定稿归档' },
    ],
    contextPillars: [
      'SAGE.md：案卷编号、密级、受众机关与全卷统一简称表',
      '受控立卷目录：01_原始依据只读保护，02_工作稿迭代，03_定稿封存',
      '跨目录只读范本库：通过 allowed_paths 挂载企业标准合同/公文母版',
      '版式与合规护栏：GB/T 9704 公文版式、金额大小写与主体全称一致性',
    ],
    subTemplates: [
      { key: 'archive_dossier_cn', label: '中国行政公文案卷 (GB/T 9704)', description: '公文版式、Excel 公式台账与归档清单核验' },
      { key: 'contract_review', label: '法务合同审查规范', description: '权利义务对等、违约上限与金额大小写一致性' },
      { key: 'document_format', label: '通用文书版式与密级', description: '标准标题层级与保密等级标注' },
    ],
    sageMdHint: '自动生成包含案卷密级、甲乙方简称表与四级目录受控约定的 SAGE.md。',
  },
  research: {
    type: 'research',
    label: '科学研究与课题',
    englishLabel: 'Source-Grounded & Hypothesis-Driven',
    positioning: '面向学术论文、基金课题与实验分析，提供零幻觉文献引用强护栏、实验四要素记录与开题至修回全周期管理。',
    defaultVcsMode: 'builtin',
    vcsLabel: '代码 Git + 手稿/数据内置快照双轨',
    directories: [
      '01_literature',
      '02_experiments_and_data',
      '03_manuscript',
      '04_submission_and_rebuttal',
    ],
    stages: [
      { id: 'proposal', label: '开题立项', hint: '研究问题 (RQ)、科学假设与文献综述矩阵' },
      { id: 'data_collection', label: '文献与数据', hint: '核心文献入库索引与数据集清洗构建' },
      { id: 'analysis', label: '实验分析', hint: '基线对比、消融实验与显著性统计检验' },
      { id: 'writing', label: '手稿撰写', hint: '论文正文图表排版与引文真实性逐条核查' },
      { id: 'submission', label: '投稿外审', hint: 'Cover Letter、补充材料与期刊格式审查' },
      { id: 'revision', label: '修回 Rebuttal', hint: '审稿人意见逐点回复矩阵与修订追踪' },
    ],
    contextPillars: [
      'SAGE.md：核心研究问题 (RQ)、科学假设与数学符号规范表 (Notation)',
      '零幻觉引文铁律：严禁编造 DOI/文献，所有学术论断必须绑定入库资料',
      '可复现实验准则：记录随机种子、超参数、均值±标准差与误差分析',
      '外部只读挂载：通过 allowed_paths 安全接入 Zotero 文献库与大型数据集',
    ],
    subTemplates: [
      { key: 'citation_strict', label: '零幻觉引用与可复现护栏', description: '强制绑定 .bib/项目资料，图表须关联数据脚本' },
      { key: 'academic_writing', label: '学术论文写作规范', description: 'APA/IEEE 引用格式、客观学术语态与实验四要素' },
      { key: 'grant_proposal', label: '基金课题申报书结构', description: '立项依据-研究内容-关键科学问题-技术路线标准框架' },
    ],
    sageMdHint: '自动生成包含研究问题 (RQ)、符号规范表与零幻觉引文护栏的 SAGE.md。',
  },
  personal: {
    type: 'personal',
    label: '个人知识空间',
    englishLabel: 'Personal Knowledge Vault',
    positioning: '面向日常笔记、读书卡片与个人事务整理，提供收件箱归档流与隐私自动脱敏保护。',
    defaultVcsMode: 'builtin',
    vcsLabel: '内置轻量历史快照',
    directories: ['00_inbox', '01_notes', '02_references', '03_archive'],
    stages: [
      { id: 'active', label: '活跃整理', hint: '日常收集、卡片沉淀与双链索引' },
      { id: 'archived', label: '归档封存', hint: '专题结项与历史笔记封存' },
    ],
    contextPillars: [
      'SAGE.md：个人知识分类体系与写作偏好',
      '结构化沉淀：结论先行与卡片式要点提炼',
      '隐私安全护栏：敏感账号、证件与凭据信息自动脱敏',
    ],
    subTemplates: [
      { key: 'concise_note_taking', label: '卡片盒双链笔记与 GTD 规范', description: '一卡一概念、结论先行与可执行行动项提炼' },
    ],
    sageMdHint: '自动生成个人知识卡片组织与隐私保护约定 SAGE.md。',
  },
};

export const ARCHETYPE_ORDER: ProjectType[] = ['coding', 'business', 'research', 'personal'];

export function getArchetypeBlueprint(type?: ProjectType | null): ArchetypeBlueprintMeta {
  return ARCHETYPE_BLUEPRINTS[type ?? 'business'] ?? ARCHETYPE_BLUEPRINTS.business;
}
