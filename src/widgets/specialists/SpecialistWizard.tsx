import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import {
  emptyPersonaSections,
  isPersonaEmpty,
  parsePersonaSections,
  serializePersonaSections,
  type PersonaSections,
} from '../../entities/specialist/personaSections';
import {
  TOOL_CAPABILITY_PACKS,
  defaultSpecialistTools,
  describeModeGate,
  packSelectionState,
  togglePackInTools,
} from '../../entities/specialist/toolCapabilities';
import { agentsApi, skillsApi, type AgentProfile, type Skill } from '../../shared/api';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';
import { ToolAllowlistEditor } from '../agents/ToolAllowlistEditor';

import { PersonaEditor } from './PersonaEditor';
import { PERMISSION_MODE_LABELS } from './SpecialistCard';
import { SpecialistPreview } from './SpecialistPreview';

const AGENT_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/u;
const AUTO_ID_PREFIX = 'specialist-';

type PermissionMode = Exclude<AgentProfile['permission_mode'], undefined>;
const PERMISSION_MODES: PermissionMode[] = [
  'read_only',
  'workspace_write',
  'prompt',
  'full_access',
];

interface SpecialistWizardProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  /** 编辑已有专家（未提供 → 创建模式）。 */
  editingAgent?: AgentProfile;
  onSaved: () => void;
}

type WizardStep = 0 | 1 | 2 | 3;
const STEP_LABELS = ['基本信息', '人设六段', '能力与权限', '预览'] as const;

function buildAutoId(): string {
  return `${AUTO_ID_PREFIX}${Date.now().toString(36)}`;
}

function defaultPermissionMode(existing?: AgentProfile['permission_mode']): PermissionMode {
  return (existing as PermissionMode | undefined) ?? 'read_only';
}

function extractAvatarAndTagline(ui: Record<string, unknown> | undefined): {
  avatar: string;
  tagline: string;
} {
  const read = (key: string): string => {
    const v = ui?.[key];
    return typeof v === 'string' ? v.trim() : '';
  };
  return { avatar: read('avatar'), tagline: read('tagline') };
}

/**
 * M1-E 专家创建/编辑向导：4 步（基本信息 → 人设六段 → 能力与权限 → 预览）。
 *
 * - 创建模式自动生成 `specialist-<ts36>` id；编辑模式从 `editingAgent` 反填
 *   表单（含 `system_prompt` 的 Markdown 解析）。
 * - 技能列表由 `skillsApi.list()` 拉取；空列表时「技能」段退化为手动输入。
 * - 预览步骤调用 `serializePersonaSections` 渲染实际写入 `system_prompt` 的内容。
 */
export function SpecialistWizard({
  open,
  onOpenChange,
  editingAgent,
  onSaved,
}: SpecialistWizardProps) {
  const [step, setStep] = useState<WizardStep>(0);
  const [submitting, setSubmitting] = useState(false);
  const [allSkills, setAllSkills] = useState<Skill[]>([]);
  const [skillsError, setSkillsError] = useState<string | null>(null);

  const [id, setId] = useState<string>(() => buildAutoId());
  const [name, setName] = useState<string>('');
  const [avatar, setAvatar] = useState<string>('');
  const [tagline, setTagline] = useState<string>('');
  const [sections, setSections] = useState<PersonaSections>(emptyPersonaSections());
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [permissionMode, setPermissionMode] = useState<PermissionMode>('read_only');
  const [tools, setTools] = useState<string[]>(() => defaultSpecialistTools());
  // 纯对话专家显式不授权任何工具；默认开启，避免新专家「静默无工具」。
  const [useTools, setUseTools] = useState(true);
  const [advancedToolsOpen, setAdvancedToolsOpen] = useState(false);

  const isEdit = !!editingAgent;

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setSubmitting(false);
    setSkillsError(null);
    if (editingAgent) {
      setId(editingAgent.id);
      setName(editingAgent.name ?? '');
      const { avatar: a, tagline: t } = extractAvatarAndTagline(editingAgent.persona_ui);
      setAvatar(a);
      setTagline(t || editingAgent.description || '');
      setSections(parsePersonaSections(editingAgent.system_prompt ?? ''));
      setSelectedSkills(editingAgent.skills ?? []);
      setPermissionMode(defaultPermissionMode(editingAgent.permission_mode));
      // 已有专家严格回填：历史上 `[]` 的专家保持无工具，由用户显式勾选后再授权。
      // 不能悄悄补默认值，否则一次编辑就会扩大该专家的工具权限。
      const existingTools = editingAgent.tools ?? [];
      setTools(existingTools);
      setUseTools(existingTools.length > 0);
      setAdvancedToolsOpen(false);
    } else {
      setId(buildAutoId());
      setName('');
      setAvatar('');
      setTagline('');
      setSections(emptyPersonaSections());
      setSelectedSkills([]);
      setPermissionMode('read_only');
      setTools(defaultSpecialistTools());
      setUseTools(true);
      setAdvancedToolsOpen(false);
    }

    skillsApi
      .list()
      .then((items) => {
        setAllSkills(items.filter((s) => s.enabled));
      })
      .catch((err) => {
        setSkillsError(err instanceof Error ? err.message : String(err));
      });
  }, [open, editingAgent]);

  const step1Error = useMemo(() => {
    if (!name.trim()) return '请输入专家名称';
    if (!isEdit && !AGENT_ID_PATTERN.test(id)) return 'ID 必须以字母/数字开头，仅含字母数字.-_';
    return '';
  }, [id, name, isEdit]);

  const step2Error = useMemo(() => {
    if (isPersonaEmpty(sections))
      return '至少填写一段人设（身份 / 职责 / 工作方式 / 风格 / 行为边界 / 输出模板任意一项）';
    return '';
  }, [sections]);

  // 门槛提示按「拒绝 / 逐次审批」分组，避免网格里每包一行小字。
  const modeGateNotices = useMemo(() => {
    const denied: string[] = [];
    const approval: string[] = [];
    if (useTools) {
      for (const pack of TOOL_CAPABILITY_PACKS) {
        if (packSelectionState(tools, pack) === 'none') continue;
        const gate = describeModeGate(permissionMode, pack);
        if (!gate) continue;
        (gate.level === 'deny' ? denied : approval).push(pack.label);
      }
    }
    return { denied, approval };
  }, [tools, permissionMode, useTools]);

  const effectiveTools = useTools ? tools : [];

  // 当前步骤的下一步可用条件；保存按钮需同时无 step1/step2 错误。
  const canAdvance = step === 0 ? !step1Error : step === 1 ? !step2Error : true;

  function advanceStep() {
    if (!canAdvance) return;
    setStep((s) => (s + 1 > 3 ? 3 : ((s + 1) as WizardStep)));
  }
  function backStep() {
    setStep((s) => (s - 1 < 0 ? 0 : ((s - 1) as WizardStep)));
  }

  async function handleSave() {
    if (step1Error || step2Error) {
      toast.error(step1Error || step2Error);
      return;
    }
    setSubmitting(true);
    try {
      const system_prompt = serializePersonaSections(sections);
      if (isEdit) {
        await agentsApi.update(editingAgent!.id, {
          name: name.trim(),
          description: tagline.trim(),
          system_prompt,
          skills: selectedSkills,
          persona_ui: { avatar: avatar.trim(), tagline: tagline.trim() },
          permission_mode: permissionMode,
          tools: effectiveTools,
        });
      } else {
        await agentsApi.create({
          id: id.trim(),
          name: name.trim(),
          role: 'specialist',
          description: tagline.trim(),
          system_prompt,
          tools: effectiveTools,
          memory_access: [],
          modelConfigData: { model: '', temperature: 0.7, max_tokens: 0 },
          maxIterations: 20,
          skills: selectedSkills,
          personaUi: { avatar: avatar.trim(), tagline: tagline.trim() },
          permissionMode,
        });
      }
      toast.success(isEdit ? '专家已更新' : '专家已创建');
      onSaved();
      onOpenChange(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`保存失败：${message}`);
    } finally {
      setSubmitting(false);
    }
  }

  function toggleSkill(skillName: string) {
    setSelectedSkills((prev) =>
      prev.includes(skillName) ? prev.filter((s) => s !== skillName) : [...prev, skillName],
    );
  }

  const dialogTitle = isEdit ? `编辑专家 · ${editingAgent!.name}` : '新建专家';
  const dialogDescription = isEdit
    ? '修改专家的名称、人设、工具能力、技能与权限后点击保存。'
    : '按四个步骤填写专家的身份、人设、工具能力、技能与权限。';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{dialogTitle}</DialogTitle>
          <DialogDescription>{dialogDescription}</DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2 border-b border-border pb-3">
          {STEP_LABELS.map((label, idx) => (
            <div key={label} className="flex items-center gap-2">
              <div
                className={`flex h-6 w-6 items-center justify-center rounded-full text-ui-xs font-medium ${
                  idx === step
                    ? 'bg-primary text-primary-foreground'
                    : idx < step
                      ? 'bg-primary/70 text-primary-foreground'
                      : 'bg-bg-subtle text-faint'
                }`}
              >
                {idx + 1}
              </div>
              <span className={idx === step ? 'text-sm font-medium' : 'text-sm text-muted'}>
                {label}
              </span>
              {idx < STEP_LABELS.length - 1 && (
                <span aria-hidden="true" className="text-border">
                  ·
                </span>
              )}
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-4">
          {step === 0 && (
            <>
              {!isEdit && (
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="specialist-wizard-id" className="text-sm font-medium">
                    专家 ID
                  </label>
                  <input
                    id="specialist-wizard-id"
                    data-testid="specialist-wizard-id"
                    value={id}
                    onChange={(e) => setId(e.target.value)}
                    pattern={AGENT_ID_PATTERN.source}
                    placeholder="specialist-writer"
                    className="rounded-radius-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                  />
                  <p className="text-ui-xs text-faint">
                    以小写字母/数字开头，仅含字母数字 <code>.</code> <code>_</code> <code>-</code>
                    。ID 一旦创建不可修改。
                  </p>
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="specialist-wizard-name" className="text-sm font-medium">
                  专家名称 <span className="text-destructive">*</span>
                </label>
                <input
                  id="specialist-wizard-name"
                  data-testid="specialist-wizard-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="公文写作专家"
                  className="rounded-radius-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </div>
              <div className="flex gap-3">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="specialist-wizard-avatar" className="text-sm font-medium">
                    头像（emoji）
                  </label>
                  <input
                    id="specialist-wizard-avatar"
                    data-testid="specialist-wizard-avatar"
                    value={avatar}
                    onChange={(e) => setAvatar(e.target.value)}
                    maxLength={4}
                    placeholder="📝"
                    className="w-20 rounded-radius-md border border-border bg-surface px-3 py-2 text-center text-xl outline-none focus:border-primary"
                  />
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <label htmlFor="specialist-wizard-tagline" className="text-sm font-medium">
                    标语
                  </label>
                  <input
                    id="specialist-wizard-tagline"
                    data-testid="specialist-wizard-tagline"
                    value={tagline}
                    onChange={(e) => setTagline(e.target.value)}
                    placeholder="一句话说明专家能做什么"
                    className="rounded-radius-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                  />
                </div>
              </div>
              {step1Error && (
                <p
                  className="text-ui-xs text-destructive"
                  data-testid="specialist-wizard-step1-error"
                >
                  {step1Error}
                </p>
              )}
            </>
          )}

          {step === 1 && (
            <div className="flex flex-col gap-2">
              <PersonaEditor sections={sections} onChange={setSections} />
              {step2Error && (
                <p
                  className="text-ui-xs text-destructive"
                  data-testid="specialist-wizard-step2-error"
                >
                  {step2Error}
                </p>
              )}
            </div>
          )}

          {step === 2 && (
            <>
              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium">权限模式</p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {PERMISSION_MODES.map((mode) => (
                    <label
                      key={mode}
                      className={`flex cursor-pointer items-start gap-2 rounded-radius-md border p-3 text-sm transition-colors ${
                        permissionMode === mode
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:bg-bg-hover'
                      }`}
                    >
                      <input
                        type="radio"
                        name="specialist-permission-mode"
                        value={mode}
                        checked={permissionMode === mode}
                        onChange={() => setPermissionMode(mode)}
                        className="mt-0.5"
                      />
                      <span className="flex flex-col">
                        <span className="font-medium">{PERMISSION_MODE_LABELS[mode]}</span>
                        <span className="text-ui-xs text-faint">
                          {mode === 'read_only' && '专家不能修改工作区文件'}
                          {mode === 'workspace_write' && '专家可以写入工作区文件'}
                          {mode === 'prompt' && '专家每次写入前需用户确认'}
                          {mode === 'full_access' && '专家可读写任意文件（谨慎）'}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium">工具能力</p>
                <p className="text-ui-xs text-faint">
                  能力包决定专家能看到并调用哪些工具；实际执行仍由权限引擎逐次裁决。
                </p>
                <div
                  role="group"
                  aria-label="工具授权方式"
                  className="flex flex-col gap-2 sm:flex-row"
                >
                  <button
                    type="button"
                    aria-pressed={useTools}
                    data-testid="specialist-wizard-use-tools"
                    onClick={() => setUseTools(true)}
                    className={`flex-1 rounded-radius-md border p-2 text-left text-sm transition-colors ${
                      useTools ? 'border-primary bg-primary/5' : 'border-border hover:bg-bg-hover'
                    }`}
                  >
                    <span className="font-medium">使用下方能力</span>
                    <span className="block text-ui-xs text-faint">
                      勾选需要的能力包，可再展开高级白名单微调
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-pressed={!useTools}
                    data-testid="specialist-wizard-no-tools"
                    onClick={() => setUseTools(false)}
                    className={`flex-1 rounded-radius-md border p-2 text-left text-sm transition-colors ${
                      !useTools ? 'border-primary bg-primary/5' : 'border-border hover:bg-bg-hover'
                    }`}
                  >
                    <span className="font-medium">不使用任何工具（纯对话）</span>
                    <span className="block text-ui-xs text-faint">
                      不能读写文件、检索记忆或调用外部能力
                    </span>
                  </button>
                </div>

                {useTools ? (
                  <>
                    <div
                      className="grid grid-cols-1 gap-1.5 sm:grid-cols-2"
                      data-testid="specialist-wizard-pack-grid"
                    >
                      {TOOL_CAPABILITY_PACKS.map((pack) => {
                        const selection = packSelectionState(tools, pack);
                        const partial = selection === 'partial';
                        return (
                          <label
                            key={pack.id}
                            className="flex items-start gap-2 rounded-radius-md border border-border p-2 text-sm"
                          >
                            <input
                              type="checkbox"
                              data-testid={`specialist-wizard-pack-${pack.id}`}
                              checked={selection === 'all'}
                              ref={(el) => {
                                if (el) el.indeterminate = partial;
                              }}
                              onChange={(e) =>
                                setTools((prev) => togglePackInTools(prev, pack, e.target.checked))
                              }
                              className="mt-0.5"
                            />
                            <span className="flex min-w-0 flex-col">
                              <span className="font-medium">
                                {pack.label}
                                {partial && (
                                  <span className="ml-1 text-ui-xs text-warning">（部分）</span>
                                )}
                              </span>
                              <span className="text-ui-xs text-faint">{pack.description}</span>
                            </span>
                          </label>
                        );
                      })}
                    </div>

                    {modeGateNotices.denied.length > 0 && (
                      <p
                        className="text-ui-xs text-warning"
                        data-testid="specialist-wizard-mode-gate-deny"
                      >
                        当前权限模式下，以下能力的写入/执行类工具会被拒绝：
                        {modeGateNotices.denied.join('、')}。调高权限模式后才会生效。
                      </p>
                    )}
                    {modeGateNotices.approval.length > 0 && (
                      <p
                        className="text-ui-xs text-warning"
                        data-testid="specialist-wizard-mode-gate-approval"
                      >
                        以下能力的写入/执行类工具每次调用都需你确认：
                        {modeGateNotices.approval.join('、')}。
                      </p>
                    )}
                    {tools.length === 0 && (
                      <p
                        className="text-ui-xs text-destructive"
                        data-testid="specialist-wizard-tools-empty"
                      >
                        未选择任何工具：专家运行时所有工具调用都会被拒绝（包括读取文件）。
                      </p>
                    )}

                    <button
                      type="button"
                      aria-expanded={advancedToolsOpen}
                      data-testid="specialist-wizard-advanced-toggle"
                      onClick={() => setAdvancedToolsOpen((prev) => !prev)}
                      className="self-start text-ui-xs text-primary hover:underline"
                    >
                      {advancedToolsOpen ? '收起高级工具白名单' : '高级：编辑工具白名单'}
                    </button>
                    {advancedToolsOpen && (
                      <ToolAllowlistEditor
                        idPrefix="specialist-wizard"
                        label="工具白名单（高级）"
                        value={tools}
                        onChange={setTools}
                      />
                    )}
                  </>
                ) : (
                  <p className="text-ui-xs text-faint">
                    纯对话专家不会暴露任何工具，也无法读取文件、检索记忆或调用外部能力。
                  </p>
                )}
              </div>

              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium">技能</p>
                {skillsError ? (
                  <p className="text-ui-xs text-warning">技能列表加载失败：{skillsError}</p>
                ) : allSkills.length === 0 ? (
                  <p className="text-ui-xs text-faint">当前工作区没有已启用的技能。</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {allSkills.map((s) => {
                      const active = selectedSkills.includes(s.name);
                      return (
                        <button
                          key={s.name}
                          type="button"
                          onClick={() => toggleSkill(s.name)}
                          aria-pressed={active}
                          className={`rounded-full border px-2.5 py-1 text-ui-xs transition-colors ${
                            active
                              ? 'border-primary bg-primary/10 text-primary'
                              : 'border-border text-text-secondary hover:bg-bg-hover'
                          }`}
                        >
                          {s.name}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          )}

          {step === 3 && (
            <SpecialistPreview
              name={name}
              avatar={avatar}
              tagline={tagline}
              sections={sections}
              skills={selectedSkills}
              permissionMode={permissionMode}
              tools={effectiveTools}
            />
          )}
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
            className="rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover disabled:opacity-50"
          >
            取消
          </button>
          {step > 0 && (
            <button
              type="button"
              onClick={backStep}
              disabled={submitting}
              className="rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover disabled:opacity-50"
            >
              上一步
            </button>
          )}
          {step < 3 ? (
            <button
              type="button"
              onClick={advanceStep}
              disabled={!canAdvance}
              className="rounded-radius-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              下一步
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSave}
              disabled={submitting || !!step1Error || !!step2Error}
              className="rounded-radius-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? '保存中…' : isEdit ? '保存更改' : '创建专家'}
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
