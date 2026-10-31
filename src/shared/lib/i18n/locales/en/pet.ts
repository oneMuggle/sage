/**
 * Desktop pet settings copy (win7 sync).
 *
 * Kept as its own domain module instead of chatAndSider so that file stays
 * under the 800-line architecture gate. Aggregated by ../../en.ts.
 */
export const enPet = {
  'settings.tab.pet': 'Desktop pet',
  'settings.pet.title': 'Desktop pet',
  'settings.pet.desc':
    'Let the Big Fish show Sage activity on your desktop: thinking, tool use, approvals, completion, and errors.',
  'settings.pet.desktop_only': 'Desktop pet is only available in the desktop app.',
  'settings.pet.enabled': 'Enable desktop pet',
  'settings.pet.enabled_desc':
    'A transparent always-on-top window. It never reads your screen and makes no extra model calls.',
  'settings.pet.display_mode': 'Display',
  'settings.pet.display.desktop': 'Desktop only',
  'settings.pet.display.in_app': 'In-app only',
  'settings.pet.display.both': 'Desktop and in-app',
  'settings.pet.display.off': 'Hidden',
  'settings.pet.size': 'Size',
  'settings.pet.size.mini': 'Mini',
  'settings.pet.size.small': 'Small',
  'settings.pet.size.medium': 'Medium',
  'settings.pet.size.large': 'Large',
  'settings.pet.size.huge': 'Huge',
  'settings.pet.tempo': 'Idle tempo',
  'settings.pet.tempo.quiet': 'Quiet',
  'settings.pet.tempo.standard': 'Standard',
  'settings.pet.tempo.lively': 'Lively',
  'settings.pet.bubble': 'Bubble',
  'settings.pet.bubble.important': 'Important states only',
  'settings.pet.bubble.always': 'Always',
  'settings.pet.bubble.off': 'Hidden',
  'settings.pet.reduce_motion': 'Reduce motion',
  'settings.pet.show_session_title': 'Show session name in bubble',
  'settings.pet.sound_waiting': 'Approval sound',
  'settings.pet.sound_error': 'Tool error sound',
  'settings.pet.sound_done': 'Completion sound',
  'settings.pet.compatibility': 'Compatibility mode',
  'settings.pet.compatibility_desc':
    'Uses an opaque window without click-through on Win7 without Aero or in remote desktop sessions.',
  'settings.pet.compat.auto': 'Auto',
  'settings.pet.compat.on': 'On',
  'settings.pet.compat.off': 'Off',
  'settings.pet.reset_position': 'Reset position',
  'settings.pet.asset_notice':
    'Assets are from dsh-pet (MIT); the full asset pack ships with the installer.',
} as const;
