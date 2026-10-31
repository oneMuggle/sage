// Browser-extension settings strings (split from chatAndSider.ts to keep the
// domain dictionary below the 800-line quality gate).
export const enChatAndSiderBrowserExtension = {
  'settings.network.extension': 'Everyday browser extension',
  'settings.network.extension.hint':
    'Share a signed-in tab from your own Chrome/Edge and Sage can use it directly. Stop sharing at any time.',
  'settings.network.extension.connected': 'Extension connected',
  'settings.network.extension.disconnected': 'Extension not connected',
  'settings.network.extension.shared': 'Using: {title} ({host})',
  'settings.network.extension.devices.empty': 'No browser extension paired yet.',
  'settings.network.extension.device.online': 'Online',
  'settings.network.extension.device.offline': 'Offline',
  'settings.network.extension.device.sharing': 'Sharing',
  'settings.network.extension.revoke': 'Revoke',
  'settings.network.extension.revoke.confirm':
    'This browser will need to pair again after revoking. Continue?',
  'settings.network.extension.revoked': 'Extension device revoked',
  'settings.network.extension.generate': 'Generate pairing code',
  'settings.network.extension.generating': 'Generating…',
  'settings.network.extension.code.title':
    'Pairing code (valid for 5 minutes, single use)',
  'settings.network.extension.code.expired':
    'This pairing code has expired. Generate a new one.',
  'settings.network.extension.code.base_url': 'Backend URL to enter in the extension',
  'settings.network.extension.code.copy': 'Copy',
  'settings.network.extension.code.copied': 'Pairing code copied',
  'settings.network.extension.install': 'Install steps',
  'settings.network.extension.install.step1':
    'Open chrome://extensions (edge://extensions in Edge) and enable Developer mode.',
  'settings.network.extension.install.step2':
    'Click "Load unpacked" and select the extension directory below.',
  'settings.network.extension.install.step3':
    'Open the extension popup, paste the pairing code; then click "Share this tab" on the target site.',
  'settings.network.extension.path': 'Extension directory',
  'settings.network.extension.path.fallback':
    'resources/extension/agent-bridge inside the install directory',
  'settings.network.extension.privacy':
    'The extension only operates the single tab you explicitly share; passwords and CAPTCHAs stay in your browser.',
  'settings.network.extension.error': 'Failed to read extension status: {error}',
  'settings.network.extension.generate_failed': 'Failed to generate pairing code: {error}',
  'settings.network.extension.revoke_failed': 'Failed to revoke device: {error}',
};
