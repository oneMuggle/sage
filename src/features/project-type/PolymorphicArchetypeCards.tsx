/**
 * Phase P2: 多形态项目专属工作台卡片与五层受控上下文水位卡 (2026-10-10)
 *
 * 1. ContextBudgetWatermarkCard — 五层受控上下文注入水位条 (L1 SAGE.md / L2 元数据与约束 / L3 项目画像 / L4 资料源 / L5 外部白名单)
 * 2. PolymorphicArchetypeCards — 按项目形态动态切换专属治理视图：
 *    - coding: 代码工程技术栈探测、规约状态与架构决策记录 (ADR)
 *    - business: 一般档案四分目录核验、Office 文书交付物台账 (.docx/.xlsx/.pptx/.pdf) 与审阅纪要
 *    - research: 科学研究核心问题 (RQ) 与实验假设矩阵、文献/实验产物台账 (.pdf/.bib/.ipynb/.csv)
 *    - personal: 个人知识空间目录分布与核心笔记沉淀
 */

import {
  Activity,
  BookOpen,
  Briefcase,
  CheckCircle2,
  Code2,
  FileSpreadsheet,
  FileText,
  FlaskConical,
  FolderCheck,
  Layers,
  Plus,
  Sparkles,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  memoryApi,
  projectApi,
  type ProjectContextBudget,
  type ProjectSummary,
  type ProjectType,
  type ProjectWorkspaceOverview,
  type WorkspaceArtifactItem,
} from '../../shared/api';
import type { ProjectProfileEntry } from '../../shared/api/types';
import { Button } from '../../shared/ui/Button';
import { Card } from '../../shared/ui/Card';

export interface PolymorphicArchetypeCardsProps {
  project: ProjectSummary;
  projectType: ProjectType;
}

const RESEARCH_CATEGORY_LABELS: Record<string, string> = {
  goal: '研究问题 (RQ)',
  architecture: '方法论框架',
  decision: '实验路线抉择',
  convention: '符号与术语表',
  note: '审稿与阶段发现',
};

function formatBytes(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function PolymorphicArchetypeCards({
  project,
  projectType,
}: PolymorphicArchetypeCardsProps) {
  const [budget, setBudget] = useState<ProjectContextBudget | null>(null);
  const [overview, setOverview] = useState<ProjectWorkspaceOverview | null>(null);
  const [profileItems, setProfileItems] = useState<ProjectProfileEntry[]>([]);
  const [decisionInput, setDecisionInput] = useState('');
  const [reasonInput, setReasonInput] = useState('');
  const [researchCategory, setResearchCategory] = useState<string>('goal');
  const [savingDecision, setSavingDecision] = useState(false);
  const [pinningPath, setPinningPath] = useState<string | null>(null);
  const [pinnedPaths, setPinnedPaths] = useState<Record<string, boolean>>({});

  const loadData = useCallback(async () => {
    const tasks: Promise<void>[] = [];
    if (typeof projectApi?.getContextBudget === 'function') {
      tasks.push(
        projectApi
          .getContextBudget(project.id)
          .then((res) => setBudget(res))
          .catch(() => setBudget(null)),
      );
    }
    if (typeof projectApi?.getWorkspaceOverview === 'function') {
      tasks.push(
        projectApi
          .getWorkspaceOverview(project.id)
          .then((res) => setOverview(res))
          .catch(() => setOverview(null)),
      );
    }
    if (typeof memoryApi?.getProjectProfile === 'function' && project.path) {
      tasks.push(
        memoryApi
          .getProjectProfile({ projectKey: project.path })
          .then((res) => setProfileItems(res?.items ?? []))
          .catch(() => setProfileItems([])),
      );
    }
    await Promise.all(tasks);
  }, [project.id, project.path]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleAddDecision = async () => {
    const trimmed = decisionInput.trim();
    if (!trimmed || savingDecision || typeof memoryApi?.createProjectProfile !== 'function') return;
    setSavingDecision(true);
    const fullContent = reasonInput.trim() ? `${trimmed} — ${reasonInput.trim()}` : trimmed;
    try {
      await memoryApi.createProjectProfile(fullContent, {
        projectKey: project.path,
        category: projectType === 'research' ? researchCategory : 'decision',
        importance: 5,
      });
      setDecisionInput('');
      setReasonInput('');
      const refreshed = await memoryApi.getProjectProfile({ projectKey: project.path });
      setProfileItems(refreshed?.items ?? []);
    } catch {
      // ignore in test/offline mode
    } finally {
      setSavingDecision(false);
    }
  };

  const handlePinArtifact = async (relativePath: string) => {
    if (pinningPath || typeof projectApi?.addMaterialFromFile !== 'function') return;
    setPinningPath(relativePath);
    try {
      await projectApi.addMaterialFromFile(project.id, relativePath);
      setPinnedPaths((prev) => ({ ...prev, [relativePath]: true }));
      await loadData();
    } catch {
      // ignore in test/offline mode
    } finally {
      setPinningPath(null);
    }
  };

  const l1Chars = budget?.l1ConventionsChars ?? 0;
  const l2Chars =
    (budget?.l2MetadataChars ??
      (project.description?.length ?? 0) + (project.instructions?.length ?? 0)) +
    (budget?.l2ConstraintsChars ?? 0);
  const l3Chars = budget?.l3ProfileChars ?? 0;
  const l4Chars = budget?.l4MaterialsChars ?? 0;
  const capChars = budget?.capChars ?? 16000;
  const totalChars = budget?.totalChars ?? l1Chars + l2Chars + l3Chars + l4Chars;
  const usagePct = Math.min(100, Math.round((totalChars / Math.max(capChars, 1)) * 100));

  const decisions = profileItems;

  return (
    <div className="space-y-4" data-testid="polymorphic-archetype-cards">
      {/* 1. 五层受控上下文注入水位条 */}
      <Card className="p-3.5 space-y-2.5" data-testid="context-budget-watermark-card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <span className="text-xs font-semibold text-foreground">
              五层受控上下文注入预算水位 (5-Layer Context Budget Watermark)
            </span>
          </div>
          <span className="text-xs font-mono text-muted-foreground">
            总注入约 {totalChars.toLocaleString()} 字符 · L4 资料池上限 {capChars.toLocaleString()}{' '}
            字符 ({usagePct}%)
          </span>
        </div>

        <div className="h-2 w-full rounded-full bg-muted overflow-hidden flex">
          <div
            className="h-full bg-primary transition-all"
            style={{ width: `${Math.max(usagePct, totalChars > 0 ? 4 : 0)}%` }}
          />
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5 text-xs">
          <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-1.5">
            <div className="text-ui-2xs text-muted-foreground">L1 隐式规约 (SAGE.md)</div>
            <div className="font-mono font-medium text-foreground">
              {l1Chars.toLocaleString()} 字 {overview?.hasSageMd ? '· 已就绪' : '· 未创建'}
            </div>
          </div>
          <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-1.5">
            <div className="text-ui-2xs text-muted-foreground">L2 元数据与强约束</div>
            <div className="font-mono font-medium text-foreground">
              {l2Chars.toLocaleString()} 字 · {budget?.enabledConstraintsCount ?? 0} 条规则
            </div>
          </div>
          <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-1.5">
            <div className="text-ui-2xs text-muted-foreground">L3 演化画像 (Profile)</div>
            <div className="font-mono font-medium text-foreground">
              {l3Chars.toLocaleString()} 字 · {decisions.length} 条记录
            </div>
          </div>
          <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-1.5">
            <div className="text-ui-2xs text-muted-foreground">L4 受控资料池 (Pinned)</div>
            <div className="font-mono font-medium text-foreground">
              {l4Chars.toLocaleString()} 字 · {budget?.activeMaterialsCount ?? 0}/
              {budget?.totalMaterialsCount ?? 0} 启用
            </div>
          </div>
          <div className="rounded border border-border/70 bg-muted/20 px-2.5 py-1.5">
            <div className="text-ui-2xs text-muted-foreground">L5 跨目录只读源</div>
            <div className="font-mono font-medium text-foreground">
              {project.allowedPaths?.length ?? 0} 个外部白名单
            </div>
          </div>
        </div>
      </Card>

      {/* 2. 多态项目专属治理工作台卡片 */}
      {projectType === 'coding' && (
        <Card className="p-4 space-y-3" data-testid="polymorphic-card-coding">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Code2 className="h-4 w-4 text-blue-500" />
              <h3 className="text-xs font-semibold text-foreground">
                代码工程专属工作台 · 工程栈探测与架构决策记录 (ADR)
              </h3>
            </div>
            <div className="flex items-center gap-1.5 text-ui-2xs">
              <span
                className={`rounded px-2 py-0.5 border ${
                  overview?.hasSageMd
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600'
                    : 'border-border bg-muted text-muted-foreground'
                }`}
              >
                SAGE.md {overview?.hasSageMd ? '已配置' : '待生成'}
              </span>
              <span
                className={`rounded px-2 py-0.5 border ${
                  overview?.hasHooksJson
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600'
                    : 'border-border bg-muted text-muted-foreground'
                }`}
              >
                hooks.json {overview?.hasHooksJson ? '已配置' : '可选'}
              </span>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2">
              <div className="text-xs font-medium text-foreground">工程标志文件与模块分布</div>
              <div className="flex flex-wrap gap-1.5">
                {(overview?.codingIndicators ?? []).length > 0 ? (
                  overview?.codingIndicators.map((ind) => (
                    <span
                      key={ind}
                      className="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 font-mono text-ui-2xs text-blue-600 dark:text-blue-400"
                    >
                      {ind}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-muted-foreground">
                    点击上方「一键初始化目录与规范」即可生成标准工程骨架
                  </span>
                )}
              </div>
              {(overview?.directorySummary ?? []).length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {overview?.directorySummary.map((d) => (
                    <span
                      key={d.name}
                      className="rounded bg-background border border-border px-2 py-0.5 font-mono text-ui-2xs text-muted-foreground"
                    >
                      {d.name}/ ({d.fileCount})
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2">
              <div className="text-xs font-medium text-foreground">
                架构决策记录 (ADR · 注入 L3 项目画像)
              </div>
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={decisionInput}
                  onChange={(e) => setDecisionInput(e.target.value)}
                  placeholder="新增架构/技术栈决策（如：采用 SQLite WAL + FTS5 索引）"
                  className="flex-1 rounded border border-input bg-background px-2 py-1 text-xs"
                  data-testid="polymorphic-decision-input"
                />
                <Button
                  size="sm"
                  onClick={() => void handleAddDecision()}
                  disabled={!decisionInput.trim() || savingDecision}
                  data-testid="polymorphic-decision-add"
                >
                  <Plus className="mr-1 h-3 w-3" />
                  记录 ADR
                </Button>
              </div>
              {decisions.length === 0 ? (
                <div className="text-ui-2xs text-muted-foreground">
                  暂无架构决策记录，添加后将自动随会话注入系统上下文。
                </div>
              ) : (
                <ul className="space-y-1 max-h-28 overflow-y-auto">
                  {decisions.slice(-4).map((d: ProjectProfileEntry) => (
                    <li
                      key={d.id}
                      className="rounded border border-border/60 bg-background px-2 py-1 text-xs"
                    >
                      <span className="font-medium text-foreground">{d.content}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}

      {projectType === 'business' && (
        <Card className="p-4 space-y-3" data-testid="polymorphic-card-business">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Briefcase className="h-4 w-4 text-emerald-500" />
              <h3 className="text-xs font-semibold text-foreground">
                一般档案项目专属工作台 · 案卷目录核验与 Office 交付物台账
              </h3>
            </div>
            <span className="text-ui-2xs text-muted-foreground">
              检测到 {overview?.officeDeliverables.length ?? 0} 份文书/报表交付物
            </span>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {/* 四分案卷目录核验 */}
            <div className="rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                <FolderCheck className="h-3.5 w-3.5 text-emerald-500" />
                标准四分案卷目录状态
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {[
                  '00_立项与背景材料',
                  '01_原始依据与佐证',
                  '02_编制中工作稿',
                  '03_定稿与签发归档',
                ].map((folderName) => {
                  const found = overview?.directorySummary.find((d) => d.name === folderName);
                  return (
                    <div
                      key={folderName}
                      className="flex items-center justify-between rounded border border-border bg-background px-2.5 py-1.5 text-xs"
                    >
                      <span className="truncate font-mono text-ui-2xs text-foreground">
                        {folderName}/
                      </span>
                      <span className="text-ui-2xs text-muted-foreground">
                        {found ? `${found.fileCount} 项` : '待初始化'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Office 文书与档案交付物台账 */}
            <div className="rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-500" />
                Office 文书与定稿交付物台账 (.docx / .xlsx / .pptx / .pdf)
              </div>
              {(overview?.officeDeliverables ?? []).length === 0 ? (
                <div className="text-xs text-muted-foreground py-2">
                  工作区暂未检出 Office 文书或 PDF 案卷。AI 生成的定稿报告与表格将自动归集于此。
                </div>
              ) : (
                <ul
                  className="space-y-1 max-h-32 overflow-y-auto"
                  data-testid="business-deliverables-list"
                >
                  {overview?.officeDeliverables.map((item: WorkspaceArtifactItem) => (
                    <li
                      key={item.relativePath}
                      className="flex items-center justify-between gap-2 rounded border border-border/60 bg-background px-2.5 py-1 text-xs"
                    >
                      <div className="flex items-center gap-1.5 min-w-0">
                        <FileText className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                        <span className="truncate font-medium text-foreground">{item.name}</span>
                        <span className="shrink-0 rounded bg-emerald-500/10 px-1.5 py-0.5 text-ui-2xs text-emerald-600">
                          {item.category}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="font-mono text-ui-2xs text-muted-foreground">
                          {formatBytes(item.sizeBytes)}
                        </span>
                        <button
                          type="button"
                          onClick={() => void handlePinArtifact(item.relativePath)}
                          disabled={pinningPath === item.relativePath || Boolean(pinnedPaths[item.relativePath])}
                          data-testid="pin-artifact-to-materials"
                          className="rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-ui-2xs text-emerald-600 hover:bg-emerald-500/20 disabled:opacity-50"
                        >
                          {pinnedPaths[item.relativePath] ? '已入库' : '纳入资料'}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}

      {projectType === 'research' && (
        <Card className="p-4 space-y-3" data-testid="polymorphic-card-research">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FlaskConical className="h-4 w-4 text-purple-500" />
              <h3 className="text-xs font-semibold text-foreground">
                科学研究专属工作台 · 核心研究问题 (RQ) 与文献/实验证据矩阵
              </h3>
            </div>
            <span className="text-ui-2xs text-muted-foreground">
              已登记 {decisions.length} 项研究问题/方法论决策 · 检出{' '}
              {overview?.researchArtifacts.length ?? 0} 份科研资产
            </span>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {/* 核心研究问题 (RQ) 与实验假设登记 */}
            <div className="rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                <Sparkles className="h-3.5 w-3.5 text-purple-500" />
                研究问题 (RQ) / 实验假设与方法论矩阵
              </div>
              <div className="flex flex-wrap gap-1.5">
                <select
                  value={researchCategory}
                  onChange={(e) => setResearchCategory(e.target.value)}
                  aria-label="选择学术画像类别"
                  data-testid="research-profile-category"
                  className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
                >
                  {Object.entries(RESEARCH_CATEGORY_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  value={decisionInput}
                  onChange={(e) => setDecisionInput(e.target.value)}
                  placeholder="登记核心研究问题或实验假设（如 RQ1: 稀疏注意力在长文档上的召回增益）"
                  className="flex-1 rounded border border-input bg-background px-2 py-1 text-xs"
                  data-testid="research-rq-input"
                />
                <input
                  type="text"
                  value={reasonInput}
                  onChange={(e) => setReasonInput(e.target.value)}
                  placeholder="证据/基准或验证方法"
                  className="w-36 rounded border border-input bg-background px-2 py-1 text-xs"
                  data-testid="research-rq-reason"
                />
                <Button
                  size="sm"
                  onClick={() => void handleAddDecision()}
                  disabled={!decisionInput.trim() || savingDecision}
                  data-testid="research-rq-add"
                >
                  <Plus className="mr-1 h-3 w-3" />
                  登记 RQ
                </Button>
              </div>
              {decisions.length === 0 ? (
                <div className="text-ui-2xs text-muted-foreground">
                  暂未登记研究问题 (RQ)。登记后将持久写入项目画像并作为科研综述与实验分析的锚点。
                </div>
              ) : (
                <ul className="space-y-1 max-h-32 overflow-y-auto" data-testid="research-rq-list">
                  {decisions.slice(-5).map((d: ProjectProfileEntry) => (
                    <li
                      key={d.id}
                      className="flex items-start gap-1.5 rounded border border-border/60 bg-background px-2.5 py-1.5 text-xs"
                    >
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-purple-500" />
                      <div className="min-w-0 flex items-center gap-1.5 flex-wrap">
                        <span className="rounded bg-purple-500/10 px-1.5 py-0.5 text-ui-2xs text-purple-600 dark:text-purple-400">
                          {RESEARCH_CATEGORY_LABELS[d.category] ?? d.category}
                        </span>
                        <span className="font-medium text-foreground">{d.content}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* 文献语料与实验数据资产台账 */}
            <div className="rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                <BookOpen className="h-3.5 w-3.5 text-purple-500" />
                文献语料 (.pdf/.bib)、实验脚本 (.ipynb) 与数据集 (.csv/.parquet)
              </div>
              {(overview?.researchArtifacts ?? []).length === 0 ? (
                <div className="text-xs text-muted-foreground py-2">
                  暂未检出文献 PDF/BibTeX、Notebook 或数据集文件。可将文献放入{' '}
                  <code className="font-mono">01-literature/</code> 或通过跨目录白名单挂载 Zotero
                  库。
                </div>
              ) : (
                <ul
                  className="space-y-1 max-h-32 overflow-y-auto"
                  data-testid="research-artifacts-list"
                >
                  {overview?.researchArtifacts.map((item: WorkspaceArtifactItem) => (
                    <li
                      key={item.relativePath}
                      className="flex items-center justify-between gap-2 rounded border border-border/60 bg-background px-2.5 py-1 text-xs"
                    >
                      <div className="flex items-center gap-1.5 min-w-0">
                        <FileText className="h-3.5 w-3.5 shrink-0 text-purple-500" />
                        <span className="truncate font-medium text-foreground">{item.name}</span>
                        <span className="shrink-0 rounded bg-purple-500/10 px-1.5 py-0.5 text-ui-2xs text-purple-600 dark:text-purple-400">
                          {item.category}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="font-mono text-ui-2xs text-muted-foreground">
                          {item.relativePath}
                        </span>
                        <button
                          type="button"
                          onClick={() => void handlePinArtifact(item.relativePath)}
                          disabled={pinningPath === item.relativePath || Boolean(pinnedPaths[item.relativePath])}
                          data-testid="pin-artifact-to-materials"
                          className="rounded border border-purple-500/40 bg-purple-500/10 px-1.5 py-0.5 text-ui-2xs text-purple-600 dark:text-purple-400 hover:bg-purple-500/20 disabled:opacity-50"
                        >
                          {pinnedPaths[item.relativePath] ? '已入库' : '纳入资料'}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}

      {projectType === 'personal' && (
        <Card className="p-4 space-y-2.5" data-testid="polymorphic-card-personal">
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-amber-500" />
            <h3 className="text-xs font-semibold text-foreground">
              个人知识空间工作台 · 笔记目录与想法沉淀
            </h3>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {['notes', 'clippings', 'outputs'].map((dir) => {
              const found = overview?.directorySummary.find((d) => d.name === dir);
              return (
                <span
                  key={dir}
                  className="rounded border border-border bg-muted/30 px-2.5 py-1 font-mono text-xs text-foreground"
                >
                  {dir}/ ({found ? `${found.fileCount} 项` : '待创建'})
                </span>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
