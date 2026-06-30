/**
 * E2E smoke test: SKILL.md spec compliance end-to-end.
 *
 * Verifies that a SKILL.md file conforming to agentskills.io spec
 * (with new license/compatibility/allowed-tools fields) loads correctly
 * in the running sage app and registers in the chat skill autocomplete.
 */

import { test, expect, _electron as electron, ElectronApplication, Page } from '@playwright/test';
import * as path from 'path';
import * as os from 'os';
import * as fs from 'fs';

const REPO_ROOT = path.resolve(__dirname, '..', '..');

test.describe('SKILL.md spec compliance (agentskills.io)', () => {
  let app: ElectronApplication;
  let page: Page;
  let tempSkillDir: string;

  test.beforeAll(async () => {
    // Create a temporary skills directory with a spec-compliant SKILL.md
    tempSkillDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sage-skills-test-'));
    const skillDir = path.join(tempSkillDir, 'spec-compliant-skill');
    fs.mkdirSync(skillDir, { recursive: true });
    fs.writeFileSync(
      path.join(skillDir, 'SKILL.md'),
      `---
name: spec-compliant-skill
description: Use this when verifying agentskills.io spec compliance
license: MIT
compatibility: Requires Python 3.10+
allowed-tools: Bash Read
---
# Spec Compliant Skill

This skill is used for E2E testing of agentskills.io spec conformance.
`,
      'utf-8',
    );

    // Launch Electron app with SAGE_SKILLS_DIR pointing to our temp dir
    app = await electron.launch({
      args: [path.join(REPO_ROOT, 'dist-electron', 'main.js')],
      env: {
        ...process.env,
        SAGE_SKILLS_DIR: tempSkillDir,
      },
    });
    page = await app.firstWindow();
    await page.waitForLoadState('load', { timeout: 30000 });
  });

  test.afterAll(async () => {
    if (app) await app.close();
    if (tempSkillDir) fs.rmSync(tempSkillDir, { recursive: true, force: true });
  });

  test('spec-compliant skill loads and registers in chat', async () => {
    // Open chat input
    const chatInput = page.getByRole('textbox', { name: /chat|message/i }).first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    // Type the skill trigger
    await chatInput.fill('/spec-compliant-skill');

    // Verify the skill is suggested in autocomplete
    const suggestion = page.getByText(/spec-compliant-skill/i).first();
    await expect(suggestion).toBeVisible({ timeout: 5000 });
  });
});
