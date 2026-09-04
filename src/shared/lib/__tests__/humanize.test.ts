/**
 * U8: humanized tool-call titles — unit tests for src/shared/lib/humanize.ts.
 *
 * Covers the plan's spec examples (write_file / read_file / run_shell /
 * search_web), Sage's real backend tool names, MCP namespacing, truncation,
 * and defensive behavior against missing/garbled args.
 */

import { describe, it, expect } from 'vitest';

import { humanizeToolCall, shortArgs } from '../humanize';

describe('humanizeToolCall — spec examples', () => {
  it('renders write_file as "Write src/App.tsx" with no scope', () => {
    // Arrange
    const args = { path: 'src/App.tsx', content: 'export default {}' };

    // Act
    const result = humanizeToolCall('write_file', args);

    // Assert
    expect(result).toEqual({ verb: 'Write', object: 'src/App.tsx' });
    expect(result.scope).toBeUndefined();
  });

  it('renders read_file as "Read src/App.tsx"', () => {
    expect(humanizeToolCall('read_file', { path: 'src/App.tsx' })).toEqual({
      verb: 'Read',
      object: 'src/App.tsx',
    });
  });

  it('renders run_shell as "Run <command>" with scope local', () => {
    expect(humanizeToolCall('run_shell', { command: 'pytest -q' })).toEqual({
      verb: 'Run',
      object: 'pytest -q',
      scope: 'local',
    });
  });

  it('renders search_web as "Search <query>" with scope external', () => {
    expect(humanizeToolCall('search_web', { query: 'tauri v2 release notes' })).toEqual({
      verb: 'Search',
      object: 'tauri v2 release notes',
      scope: 'external',
    });
  });
});

describe('humanizeToolCall — Sage backend tools', () => {
  it('renders terminal (Sage shell tool) with scope local', () => {
    expect(humanizeToolCall('terminal', { command: 'npm run dev', cwd: '/x' })).toEqual({
      verb: 'Run',
      object: 'npm run dev',
      scope: 'local',
    });
  });

  it('renders bash with scope local', () => {
    expect(humanizeToolCall('bash', { command: 'npm run dev', cwd: '/x' })).toEqual({
      verb: 'Run',
      object: 'npm run dev',
      scope: 'local',
    });
  });

  it('renders bash background launch the same as foreground', () => {
    expect(humanizeToolCall('bash', { command: 'npm run dev', run_in_background: true })).toEqual({
      verb: 'Run',
      object: 'npm run dev',
      scope: 'local',
    });
  });

  it('renders bash_output with the shell id', () => {
    expect(humanizeToolCall('bash_output', { shell_id: 'abc123' })).toEqual({
      verb: 'Read output of',
      object: 'abc123',
      scope: 'local',
    });
  });

  it('renders kill_shell with the shell id', () => {
    expect(humanizeToolCall('kill_shell', { shell_id: 'abc123' })).toEqual({
      verb: 'Kill',
      object: 'abc123',
      scope: 'local',
    });
  });

  it('falls back to a placeholder when bash_output has no shell id', () => {
    expect(humanizeToolCall('bash_output', {})).toEqual({
      verb: 'Read output of',
      object: 'a background shell',
      scope: 'local',
    });
  });

  it('renders web_search (Sage name) with scope external', () => {
    expect(humanizeToolCall('web_search', { query: 'python asyncio' })).toEqual({
      verb: 'Search',
      object: 'python asyncio',
      scope: 'external',
    });
  });

  it('renders web_fetch with the URL host only, scope external', () => {
    const result = humanizeToolCall('web_fetch', {
      url: 'https://docs.python.org/3/library/asyncio.html?x=1',
    });
    expect(result).toEqual({ verb: 'Fetch', object: 'docs.python.org', scope: 'external' });
  });

  it('falls back to the raw url string when web_fetch url is unparseable', () => {
    expect(humanizeToolCall('web_fetch', { url: 'not a url' })).toEqual({
      verb: 'Fetch',
      object: 'not a url',
      scope: 'external',
    });
  });

  it('renders edit_file using the file_path argument', () => {
    expect(humanizeToolCall('edit_file', { file_path: 'backend/main.py', new_string: '' })).toEqual(
      {
        verb: 'Edit',
        object: 'backend/main.py',
      },
    );
  });

  it('renders write_file in append mode as "Append to"', () => {
    expect(humanizeToolCall('write_file', { path: 'log.txt', content: 'x', append: true })).toEqual(
      {
        verb: 'Append to',
        object: 'log.txt',
      },
    );
  });

  it('renders list_dir, glob_search and grep_search', () => {
    expect(humanizeToolCall('list_dir', { path: 'src/widgets' }).verb).toBe('List');
    expect(humanizeToolCall('glob_search', { pattern: '**/*.tsx' })).toEqual({
      verb: 'Find',
      object: '**/*.tsx',
    });
    expect(humanizeToolCall('grep_search', { pattern: 'TODO' })).toEqual({
      verb: 'Search',
      object: 'TODO',
    });
  });

  it('renders memory tools with human verbs', () => {
    expect(humanizeToolCall('memory_search', { query: '端口约定' })).toEqual({
      verb: 'Recall',
      object: '端口约定',
    });
    expect(humanizeToolCall('memory_save', { content: '后端端口是 8765' })).toEqual({
      verb: 'Remember',
      object: '后端端口是 8765',
    });
  });

  it('renders todo_write with the item count (plural and singular)', () => {
    expect(
      humanizeToolCall('todo_write', {
        todos: [
          { content: 'a', status: 'pending' },
          { content: 'b', status: 'done' },
        ],
      }),
    ).toEqual({ verb: 'Update plan', object: '2 items' });
    expect(humanizeToolCall('todo_write', { todos: [{ content: 'a' }] })).toEqual({
      verb: 'Update plan',
      object: '1 item',
    });
  });

  it('renders calculator, agent, ask_user_question and skill', () => {
    expect(humanizeToolCall('calculator', { expression: '2 + 2' })).toEqual({
      verb: 'Calculate',
      object: '2 + 2',
    });
    expect(humanizeToolCall('agent', { description: 'review auth module' })).toEqual({
      verb: 'Delegate',
      object: 'review auth module',
    });
    expect(humanizeToolCall('ask_user_question', { question: '要用哪个端口？' })).toEqual({
      verb: 'Ask',
      object: '要用哪个端口？',
    });
    expect(humanizeToolCall('skill', { skill: 'dataviz' })).toEqual({
      verb: 'Use skill',
      object: 'dataviz',
    });
  });

  it('renders the repl tool with the first line of code, scope local', () => {
    const result = humanizeToolCall('repl', { code: 'import os\nprint(os.getcwd())' });
    expect(result).toEqual({ verb: 'Run', object: 'import os', scope: 'local' });
  });

  // ---- runtime / dev-env assistant (2026-09) ----
  it('renders runtime_probe as "Probe <language list>"', () => {
    expect(humanizeToolCall('runtime_probe', { languages: ['python', 'javascript'] })).toEqual({
      verb: 'Probe',
      object: 'python, javascript',
    });
  });

  it('renders runtime_probe with no languages as "Probe available runtimes"', () => {
    expect(humanizeToolCall('runtime_probe', {})).toEqual({
      verb: 'Probe',
      object: 'available runtimes',
    });
  });

  it('renders project_diagnose as "Diagnose <project_root or workspace>"', () => {
    expect(humanizeToolCall('project_diagnose', { project_root: '/home/dev/sage' })).toEqual({
      verb: 'Diagnose',
      object: '/home/dev/sage',
    });
    expect(humanizeToolCall('project_diagnose', {})).toEqual({
      verb: 'Diagnose',
      object: 'workspace',
    });
  });

  it('renders runtime_exec as "Run in <language>" with scope local', () => {
    expect(
      humanizeToolCall('runtime_exec', { language: 'python', code: 'print(1)' }),
    ).toEqual({
      verb: 'Run in',
      object: 'python',
      scope: 'local',
    });
  });
});

describe('humanizeToolCall — MCP and subagent names', () => {
  it('renders mcp__<server>__<tool> as "Use <server> · <tool>" with scope external', () => {
    expect(humanizeToolCall('mcp__drawio__render_diagram', {})).toEqual({
      verb: 'Use',
      object: 'drawio · render_diagram',
      scope: 'external',
    });
  });

  it('renders the synthetic "subagent: <desc>" name as delegation', () => {
    expect(humanizeToolCall('subagent: sweep dead refs', {})).toEqual({
      verb: 'Delegate',
      object: 'sweep dead refs',
    });
  });
});

describe('humanizeToolCall — unknown tools and defensive input', () => {
  it('falls back to the raw name plus compact args for unknown tools', () => {
    expect(humanizeToolCall('brand_new_tool', { foo: 'bar', n: 1 })).toEqual({
      verb: 'brand_new_tool',
      object: 'foo=bar  n=1',
    });
  });

  it('returns an empty object segment for unknown tools without args', () => {
    expect(humanizeToolCall('mystery', undefined)).toEqual({ verb: 'mystery', object: '' });
  });

  it('does not throw on null args for known tools', () => {
    expect(humanizeToolCall('read_file', null)).toEqual({ verb: 'Read', object: 'a file' });
    expect(humanizeToolCall('terminal', null)).toEqual({
      verb: 'Run',
      object: 'a command',
      scope: 'local',
    });
  });

  it('uses fallback nouns when a known arg key is missing or blank', () => {
    expect(humanizeToolCall('write_file', { path: '   ' }).object).toBe('a file');
    expect(humanizeToolCall('web_search', {}).scope).toBe('external');
  });

  it('truncates overlong objects to keep the title one line', () => {
    const longCmd = 'echo ' + 'x'.repeat(200);
    const result = humanizeToolCall('run_shell', { command: longCmd });
    expect(result.object.length).toBeLessThanOrEqual(80);
    expect(result.object.endsWith('…')).toBe(true);
  });
});

describe('shortArgs', () => {
  it('joins key=value pairs and flattens newlines', () => {
    expect(shortArgs({ path: 'a/b.txt', content: 'line1\nline2' })).toBe(
      'path=a/b.txt  content=line1 line2',
    );
  });

  it('JSON-encodes non-string values', () => {
    expect(shortArgs({ n: 3, ok: true, list: [1, 2] })).toBe('n=3  ok=true  list=[1,2]');
  });

  it('truncates very long values', () => {
    const out = shortArgs({ big: 'y'.repeat(500) });
    expect(out.length).toBeLessThanOrEqual('big='.length + 96);
    expect(out).toContain('…');
  });

  it('returns empty string for nullish input', () => {
    expect(shortArgs(null)).toBe('');
    expect(shortArgs(undefined)).toBe('');
  });
});
