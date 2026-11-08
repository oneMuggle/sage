import { ReferenceManager } from '../../../features/project-type';

export interface FilesSectionProps {
  projectId: string;
}

export function FilesSection({ projectId }: FilesSectionProps) {
  return <ReferenceManager projectId={projectId} />;
}
