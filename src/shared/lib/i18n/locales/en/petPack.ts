/**
 * Desktop pet animation-pack settings copy.
 *
 * Split out of chatAndSider.ts: that aggregate dictionary sits at the 800-line
 * architecture gate, so new keys live here. Aggregated by ../../en.ts.
 */
export const enPetPack = {
  'settings.pet.pack': 'Animation pack',
  'settings.pet.pack_desc':
    'Use the built-in Big Fish, or import a custom zip pack (webm/mp4/webp/png assets only; scripts inside the archive are never executed).',
  'settings.pet.pack_builtin': 'Big Fish (built-in)',
  'settings.pet.pack_missing': 'missing',
  'settings.pet.pack_actions': 'Pack management',
  'settings.pet.pack_builtin_desc':
    'Built-in assets are from dsh-pet (MIT). Importing a custom pack switches to it automatically.',
  'settings.pet.pack_import': 'Import pack…',
  'settings.pet.pack_import_busy': 'Importing…',
  'settings.pet.pack_export': 'Export',
  'settings.pet.pack_delete': 'Delete',
  'settings.pet.pack_delete_confirm': 'Confirm delete?',
  'settings.pet.pack_imported': 'Imported and switched: ',
  'settings.pet.pack_exported': 'Exported: ',
  'settings.pet.pack_deleted': 'Pack deleted',
  'settings.pet.pack_failed': 'Action failed',
} as const;
