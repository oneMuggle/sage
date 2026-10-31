/**
 * Desktop pet animation-pack and multi-pet settings copy.
 *
 * Split out of chatAndSider.ts: that aggregate dictionary sits at the 800-line
 * architecture gate, so new keys live here. Aggregated by ../../en.ts.
 */
export const enPetPack = {
  'settings.pet.pets': 'Pets',
  'settings.pet.pets_desc':
    'Up to 3 pets; each can use its own animation pack and size, with an independent position.',
  'settings.pet.pet_label': 'Pet',
  'settings.pet.add_pet': 'Add pet',
  'settings.pet.remove_pet': 'Remove',
  'settings.pet.pets_max': 'Up to 3 pets',
<<<<<<< HEAD
=======
  'settings.pet.external_api': 'Local read-only status API',
  'settings.pet.external_api_desc':
    'Serves GET /v1/health and /v1/status on a random 127.0.0.1 port. Requests need a Bearer token; the port and token are written to pet-api.json in the user data directory. Read-only — it cannot control Sage.',
  'settings.pet.external_api_port': 'Port {port}',
  'settings.pet.external_api_starting': 'Starting…',
  'settings.pet.external_api_failed': 'Failed to start',
>>>>>>> origin/main
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
