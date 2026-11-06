// 通知偏好持久化测试 (2026-11-05)
// 覆盖路径解析、默认值、往返读写与损坏文件回退。
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  DEFAULT_NOTIFICATION_PREFS,
  getNotificationPrefsPath,
  readNotificationPrefs,
  writeNotificationPrefs,
} from '../notificationPrefs';

describe('notificationPrefs', () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'sage-notif-'));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it('打包模式写到 userData，开发模式写到 cwd/data', () => {
    expect(getNotificationPrefsPath(true, '/user-data', '/repo')).toBe(
      join('/user-data', 'sage-notification-prefs.json'),
    );
    expect(getNotificationPrefsPath(false, '/user-data', '/repo')).toBe(
      join('/repo', 'data', 'sage-notification-prefs.json'),
    );
  });

  it('文件不存在时返回默认全开', () => {
    expect(readNotificationPrefs(join(dir, 'missing.json'))).toEqual(DEFAULT_NOTIFICATION_PREFS);
  });

  it('写入后能原样读回', () => {
    const path = join(dir, 'prefs.json');
    writeNotificationPrefs(path, {
      enabled: false,
      backgroundTasks: true,
      webhookUrl: 'https://hook.example/x',
      slackWebhookUrl: 'https://hooks.slack.com/y',
    });
    expect(readNotificationPrefs(path)).toEqual({
      enabled: false,
      backgroundTasks: true,
      webhookUrl: 'https://hook.example/x',
      slackWebhookUrl: 'https://hooks.slack.com/y',
    });
  });

  it('字段缺失按开启处理（升级用户不被静默静音）', () => {
    const path = join(dir, 'partial.json');
    writeFileSync(path, JSON.stringify({ enabled: false }), 'utf-8');
    expect(readNotificationPrefs(path)).toEqual({
      enabled: false,
      backgroundTasks: true,
      webhookUrl: '',
      slackWebhookUrl: '',
    });
  });

  it('损坏的 JSON 回退默认值', () => {
    const path = join(dir, 'broken.json');
    writeFileSync(path, '{not json', 'utf-8');
    expect(readNotificationPrefs(path)).toEqual(DEFAULT_NOTIFICATION_PREFS);
  });
});
