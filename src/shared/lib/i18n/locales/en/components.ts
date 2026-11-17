/**
 * English strings for offline component packages (.sagepkg).
 *
 * Kept as its own domain module instead of growing chatAndSider.ts.
 */
export const enComponents = {
  'settings.tab.components': 'Components',
  'settings.components.title': 'Offline components',
  'settings.components.desc':
    'Import administrator-signed .sagepkg bundles (models, OCR, and more) without internet access.',
  'settings.components.import': 'Import .sagepkg',
  'settings.components.scan': 'Scan packages',
  'settings.components.refresh': 'Refresh',
  'settings.components.installed_title': 'Installed components',
  'settings.components.installed_empty': 'No offline components installed yet.',
  'settings.components.discovered_title': 'Discovered packages',
  'settings.components.discovered_empty': 'No importable component packages found.',
  'settings.components.remove': 'Remove',
  'settings.components.remove_confirm':
    'Remove component "{name}"? You will need to import it again to restore it.',
  'settings.components.import_success': 'Import complete. Restart Sage to apply.',
  'settings.components.remove_success': 'Component removed.',
  'settings.components.scan_success': 'Scan complete; importable packages were found.',
  'settings.components.scan_empty': 'Scan complete; no component packages found.',
  'settings.components.error': 'Component operation failed. Check logs or use Sage Doctor.',
  'settings.components.unsupported': 'Component management is only available in the desktop app.',
  'settings.components.importing': 'Importing component package…',
  'settings.components.signature_ok': 'Signature verified',
  'settings.components.security_note':
    'Only signed component packages are accepted; production machines never run pip/npm. Win7 packages must be built with Python 3.8.',
} as const;
