/** Project workbench · file-references dictionary — English. */
import type { GovernanceFilesTranslationKey } from '../zh/governanceFiles';

export const enGovernanceFiles: Record<GovernanceFilesTranslationKey, string> = {
  'governance.files.subtitle': 'File references grant read-only access to external resources.',
  'governance.files.scan.idle': 'Rescan',
  'governance.files.scan.busy': 'Scanning...',
  'governance.files.create.title': 'Add reference',
  'governance.files.create.relPath': 'Project-relative path *',
  'governance.files.create.targetPath': 'Target absolute path *',
  'governance.files.create.alias': 'Alias',
  'governance.files.create.kind': 'Type',
  'governance.files.create.kind.directory': 'Directory',
  'governance.files.create.kind.file': 'File',
  'governance.files.create.kind.symlink': 'Symlink',
  'governance.files.create.submitting': 'Adding...',
  'governance.files.create.submit': 'Add reference',
  'governance.files.list.loading': 'Loading references...',
  'governance.files.list.empty':
    'No references yet. Add one above, or click "Rescan" to pick up project symlinks.',
  'governance.files.row.created': 'Created',
  'governance.files.confirm.title': 'Delete reference?',
  'governance.files.confirm.messageTail': 'will be removed. The underlying files stay on disk.',
  'governance.files.confirm.delete': 'Delete',
};
