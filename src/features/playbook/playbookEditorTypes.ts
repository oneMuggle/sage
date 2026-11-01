/** 规程编辑器表单类型（2026-11-01，从 PlaybookSpecEditor 拆出）。 */
export interface ArtifactForm {
  id: string;
  label: string;
  globs: string;
  targetDir: string;
  required: boolean;
}

export interface RuleForm {
  templateKey: string;
  content: string;
  category: string;
  triggerPattern: string;
  priority: number;
}

export interface MilestoneForm {
  title: string;
  description: string;
}

export interface CriterionForm {
  id: string;
  label: string;
  type: 'manual' | 'artifact';
  artifactId: string;
}

export interface StageForm {
  id: string;
  label: string;
  objective: string;
  artifacts: ArtifactForm[];
  rules: RuleForm[];
  milestones: MilestoneForm[];
  criteria: CriterionForm[];
}

export interface FormState {
  name: string;
  description: string;
  stages: StageForm[];
}
