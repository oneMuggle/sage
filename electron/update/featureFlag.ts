// electron/update/featureFlag.ts
import { app } from 'electron';

export const ENABLE_UPDATE_PROVIDERS_UI = (): boolean =>
  process.env.SAGE_EXPERIMENTAL_PROVIDERS === '1' || app.isPackaged === false;

export const BUILTIN_GENERIC_CONFIG = {
  id: '__builtin__',
  type: 'generic-http',
  displayName: 'Official (updates.sage.app)',
  enabled: true,
  isDefault: false, // 仅在用户没配置 default 时启用
  createdAt: '',
  updatedAt: '',
  config: {
    manifestUrl: 'https://updates.sage.app/api/v1/updates/latest',
    publicKey: `-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA28+4qGf6PSfwqA97ST5x
+3MW1Udtg9UJDB2gL5CP55tRM2kMg3qFkk3bY548BgJsAVEZxRyE+jS6cS4sTKEK
+6I3cwt67NDUqefXstGiEqj+h8PqdXXMwaXO7aaL9WwNA1f49vtfsyOcbaUbPicG
uyJ2efXQYXFNg0eSvRNgbH4CKiz1jL0EWkONwY5T2m6xX/aK9o8hR5KW3E42gAFE
8KVCn4tpqhJDRzPbsTLqvkE9HeiszzLloOrYpD1FtG8l9kYOEtdgwJRnHxj5S4Tx
eL4qD6nEtJM2cWF6FbYrVWSf6MrUkOtGERYRjad0jgfd0fqk0V7zgR5uFgFbvyKV
5QIDAQAB
-----END PUBLIC KEY-----`,
    channelMap: { stable: true, beta: true, alpha: true },
    requireArtifactSignature: true as const,
  },
};