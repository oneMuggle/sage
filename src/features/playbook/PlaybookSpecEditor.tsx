/**
 * PlaybookSpecEditor — 结构化表单 + JSON 高级视图。
 *
 * 表单只编辑名称、描述、阶段与产物（label/globs/target_dir/required）；
 * 规则、里程碑、内容检查等高级字段保留在 JSON 视图中编辑。
 */
import { useState } from 'react';

import type {
  PlaybookArtifactSpec,
  PlaybookSpec,
  PlaybookStageSpec,
} from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

export interface PlaybookSpecEditorProps {
  spec: PlaybookSpec;
  saving: boolean;
  error: string | null;
  onSave: (spec: PlaybookSpec) => void;
  onCancel: () => void;
}

interface ArtifactForm {
  id: string;
  label: string;
  globs: string;
  targetDir: string;
  required: boolean;
}

interface StageForm {
  id: string;
  label: string;
  objective: string;
  artifacts: ArtifactForm[];
}

interface FormState {
  name: string;
  description: string;
  stages: StageForm[];
}

function toForm(spec: PlaybookSpec): FormState {
  return {
    name: spec.name,
    description: spec.description ?? '',
    stages: (spec.stages ?? []).map((stage) => ({
      id: stage.id,
      label: stage.label ?? '',
      objective: stage.objective ?? '',
      artifacts: (stage.artifacts ?? []).map((artifact) => ({
        id: artifact.id,
        label: artifact.label ?? '',
        globs: (artifact.match?.globs ?? []).join(', '),
        targetDir: artifact.target_dir ?? '',
        required: artifact.required !== false,
      })),
    })),
  };
}

function toSpec(spec: PlaybookSpec, form: FormState): PlaybookSpec {
  const originalStages = spec.stages ?? [];
  const stages: PlaybookStageSpec[] = form.stages.map((stage, stageIndex) => {
    const original =
      originalStages.find((item) => item.id === stage.id) ?? originalStages[stageIndex];
    const artifacts: PlaybookArtifactSpec[] = stage.artifacts.map((artifact, artifactIndex) => {
      const previous =
        (original?.artifacts ?? []).find((item) => item.id === artifact.id) ??
        (original?.artifacts ?? [])[artifactIndex];
      const globs = artifact.globs
        .split(/[,\n]/)
        .map((item) => item.trim())
        .filter(Boolean);
      return {
        ...(previous ?? {}),
        id: artifact.id || previous?.id || `artifact-${stageIndex + 1}-${artifactIndex + 1}`,
        label: artifact.label,
        required: artifact.required,
        target_dir: artifact.targetDir.trim() || null,
        match: {
          ...(previous?.match ?? {}),
          globs,
          min_bytes: previous?.match?.min_bytes ?? 0,
          min_count: previous?.match?.min_count ?? 1,
          max_age_days: previous?.match?.max_age_days ?? null,
        },
        content_checks: previous?.content_checks ?? [],
        missing_action: previous?.missing_action ?? null,
      } as PlaybookArtifactSpec;
    });
    return {
      ...(original ?? {}),
      id: stage.id || `stage-${stageIndex + 1}`,
      label: stage.label,
      order: stageIndex + 1,
      objective: stage.objective,
      artifacts,
      exit_criteria: original?.exit_criteria ?? [],
      rules: original?.rules ?? [],
      recommended_milestones: original?.recommended_milestones ?? [],
    } as PlaybookStageSpec;
  });
  return {
    ...spec,
    name: form.name.trim(),
    description: form.description.trim(),
    stages,
  };
}

export function PlaybookSpecEditor({
  spec,
  saving,
  error,
  onSave,
  onCancel,
}: PlaybookSpecEditorProps) {
  const [mode, setMode] = useState<'form' | 'json'>('form');
  const [form, setForm] = useState<FormState>(() => toForm(spec));
  const [jsonDraft, setJsonDraft] = useState(() => JSON.stringify(spec, null, 2));
  const [localError, setLocalError] = useState<string | null>(null);

  const updateStage = (index: number, patch: Partial<StageForm>) => {
    setForm((prev) => ({
      ...prev,
      stages: prev.stages.map((stage, stageIndex) =>
        stageIndex === index ? { ...stage, ...patch } : stage,
      ),
    }));
  };

  const updateArtifact = (
    stageIndex: number,
    artifactIndex: number,
    patch: Partial<ArtifactForm>,
  ) => {
    setForm((prev) => ({
      ...prev,
      stages: prev.stages.map((stage, index) =>
        index === stageIndex
          ? {
              ...stage,
              artifacts: stage.artifacts.map((artifact, artifactIndex2) =>
                artifactIndex2 === artifactIndex ? { ...artifact, ...patch } : artifact,
              ),
            }
          : stage,
      ),
    }));
  };

  const handleSave = () => {
    setLocalError(null);
    if (mode === 'json') {
      try {
        const parsed = JSON.parse(jsonDraft) as PlaybookSpec;
        onSave(parsed);
      } catch (err) {
        setLocalError('JSON 解析失败：' + (err instanceof Error ? err.message : String(err)));
      }
      return;
    }
    if (!form.name.trim()) {
      setLocalError('规程名称不能为空');
      return;
    }
    for (const stage of form.stages) {
      if (!stage.label.trim()) {
        setLocalError('阶段名称不能为空');
        return;
      }
      for (const artifact of stage.artifacts) {
        if (!artifact.label.trim() || !artifact.globs.trim()) {
          setLocalError('产物名称与匹配 glob 不能为空');
          return;
        }
      }
    }
    onSave(toSpec(spec, form));
  };

  return (
    <div className="space-y-3 rounded-md border border-border p-3" data-testid="playbook-editor">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-medium text-foreground">编辑项目规程</div>
        <div className="flex gap-1">
          <Button
            size="sm"
            variant={mode === 'form' ? 'primary' : 'secondary'}
            onClick={() => setMode('form')}
            data-testid="playbook-editor-mode-form"
          >
            表单
          </Button>
          <Button
            size="sm"
            variant={mode === 'json' ? 'primary' : 'secondary'}
            onClick={() => {
              setJsonDraft(JSON.stringify(toSpec(spec, form), null, 2));
              setMode('json');
            }}
            data-testid="playbook-editor-mode-json"
          >
            JSON
          </Button>
        </div>
      </div>

      {mode === 'form' ? (
        <div className="space-y-3" data-testid="playbook-editor-form">
          <label className="block text-xs text-muted-foreground">
            规程名称
            <input
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
              data-testid="playbook-editor-name"
            />
          </label>
          <label className="block text-xs text-muted-foreground">
            描述
            <textarea
              value={form.description}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, description: event.target.value }))
              }
              rows={2}
              className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
            />
          </label>
          {form.stages.map((stage, stageIndex) => (
            <div
              key={stage.id || stageIndex}
              className="space-y-2 rounded-md border border-border p-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={stage.label}
                  onChange={(event) => updateStage(stageIndex, { label: event.target.value })}
                  placeholder="阶段名称"
                  className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
                />
                <input
                  value={stage.objective}
                  onChange={(event) =>
                    updateStage(stageIndex, { objective: event.target.value })
                  }
                  placeholder="阶段目标"
                  className="flex-[2] rounded-md border border-input bg-background px-2 py-1 text-xs"
                />
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    setForm((prev) => ({
                      ...prev,
                      stages: prev.stages.filter((_, index) => index !== stageIndex),
                    }))
                  }
                >
                  删除阶段
                </Button>
              </div>
              {stage.artifacts.map((artifact, artifactIndex) => (
                <div
                  key={artifact.id || artifactIndex}
                  className="space-y-1 border-t border-border pt-2"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={artifact.label}
                      onChange={(event) =>
                        updateArtifact(stageIndex, artifactIndex, {
                          label: event.target.value,
                        })
                      }
                      placeholder="产物名称"
                      className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
                    />
                    <input
                      value={artifact.targetDir}
                      onChange={(event) =>
                        updateArtifact(stageIndex, artifactIndex, {
                          targetDir: event.target.value,
                        })
                      }
                      placeholder="目标目录（可选）"
                      className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
                    />
                    <label className="flex items-center gap-1 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={artifact.required}
                        onChange={(event) =>
                          updateArtifact(stageIndex, artifactIndex, {
                            required: event.target.checked,
                          })
                        }
                      />
                      必需
                    </label>
                  </div>
                  <input
                    value={artifact.globs}
                    onChange={(event) =>
                      updateArtifact(stageIndex, artifactIndex, {
                        globs: event.target.value,
                      })
                    }
                    placeholder="匹配 glob（逗号分隔）"
                    className="w-full rounded-md border border-input bg-background px-2 py-1 font-mono text-xs"
                    data-testid={`playbook-editor-globs-${artifact.id || artifactIndex}`}
                  />
                </div>
              ))}
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  updateStage(stageIndex, {
                    artifacts: [
                      ...stage.artifacts,
                      {
                        id: `artifact-${stageIndex + 1}-${stage.artifacts.length + 1}`,
                        label: '',
                        globs: '',
                        targetDir: '',
                        required: true,
                      },
                    ],
                  })
                }
              >
                添加产物
              </Button>
            </div>
          ))}
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              setForm((prev) => ({
                ...prev,
                stages: [
                  ...prev.stages,
                  {
                    id: `stage-${prev.stages.length + 1}`,
                    label: '',
                    objective: '',
                    artifacts: [],
                  },
                ],
              }))
            }
          >
            添加阶段
          </Button>
        </div>
      ) : (
        <textarea
          value={jsonDraft}
          onChange={(event) => setJsonDraft(event.target.value)}
          rows={14}
          spellCheck={false}
          className="w-full rounded-md border border-input bg-background px-2 py-1 font-mono text-xs text-foreground"
          data-testid="playbook-spec-editor"
        />
      )}

      {(localError || error) && (
        <div className="text-xs text-destructive">{localError || error}</div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          onClick={handleSave}
          disabled={saving}
          data-testid="playbook-save-spec"
        >
          {saving ? '保存中…' : '保存为新版本'}
        </Button>
        <Button size="sm" variant="secondary" onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}

export default PlaybookSpecEditor;
