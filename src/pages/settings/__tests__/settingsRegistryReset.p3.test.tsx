// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { getSettingMetadata } from '../../../entities/setting/settingsRegistry';
import { I18nProvider } from '../../../shared/lib/i18n';
import { SettingRow, Toggle } from '../components';

const SETTINGS_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');

function renderZh(ui: ReactElement) {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
}

function literalAnchors(fileName: string, prefix: string): string[] {
  const content = readFileSync(join(SETTINGS_DIR, fileName), 'utf8');
  return Array.from(content.matchAll(/\banchor="([^"]+)"/g), (m) => m[1])
    .filter((value) => value.startsWith(prefix))
    .sort();
}

describe('SettingRow 恢复默认 (P3)', () => {
  it('renders the reset control only when the value differs from the registry default', () => {
    // streaming 的 registry 默认值是 true。
    const { rerender } = renderZh(
      <SettingRow label="流式输出" anchor="streaming" value={false} onReset={() => {}}>
        <Toggle value={false} onChange={() => {}} />
      </SettingRow>,
    );
    expect(screen.getByTestId('setting-reset-streaming')).toBeInTheDocument();

    rerender(
      <I18nProvider defaultLocale="zh">
        <SettingRow label="流式输出" anchor="streaming" value onReset={() => {}}>
          <Toggle value onChange={() => {}} />
        </SettingRow>
      </I18nProvider>,
    );
    expect(screen.queryByTestId('setting-reset-streaming')).not.toBeInTheDocument();
  });

  it('invokes onReset when clicked', () => {
    const onReset = vi.fn();
    renderZh(
      <SettingRow label="流式输出" anchor="streaming" value={false} onReset={onReset}>
        <Toggle value={false} onChange={() => {}} />
      </SettingRow>,
    );
    fireEvent.click(screen.getByTestId('setting-reset-streaming'));
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(screen.getByText('恢复默认')).toBeInTheDocument();
  });

  it('renders no reset control without onReset even when the value is dirty', () => {
    renderZh(
      <SettingRow label="流式输出" anchor="streaming" value={false}>
        <Toggle value={false} onChange={() => {}} />
      </SettingRow>,
    );
    expect(screen.queryByTestId('setting-reset-streaming')).not.toBeInTheDocument();
  });

  it('renders no reset control for anchors missing from the registry', () => {
    const { container } = renderZh(
      <SettingRow label="未登记项" anchor="not-a-registered-key" value={1} onReset={() => {}}>
        <span>control</span>
      </SettingRow>,
    );
    expect(container.querySelector('[data-testid^="setting-reset-"]')).toBeNull();
  });
});

describe('编排 / 更新 tab 的 registry 覆盖 (P3)', () => {
  it('every literal orch anchor in OrchestrationTab has registry metadata', () => {
    const anchors = literalAnchors('OrchestrationTab.tsx', 'orch.');
    expect(anchors.length).toBeGreaterThan(0);
    const missing = anchors.filter((anchor) => getSettingMetadata(anchor) === undefined);
    expect(missing).toEqual([]);
  });

  it('keeps every updates anchor in UpdatesTab collapsible as advanced', () => {
    const anchors = literalAnchors('UpdatesTab.tsx', 'updates.');
    expect(anchors).toEqual([
      'updates.autoRollbackThreshold',
      'updates.cacheRetentionDays',
      'updates.checkIntervalHours',
      'updates.enableTelemetry',
      'updates.rollbackWindowDays',
      'updates.updateServerUrl',
    ]);
    const notAdvanced = anchors.filter(
      (anchor) => getSettingMetadata(anchor)?.visibility !== 'advanced',
    );
    expect(notAdvanced).toEqual([]);
  });
});
