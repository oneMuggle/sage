/**
 * U8 (sage-optimization): humanized tool-call titles.
 *
 * The agent stream carries machine-shaped tool calls — `write_file(path=...)` —
 * which read like a debugger, not an assistant. This module synthesizes a
 * one-line human sentence per call: "Write **src/App.tsx**", "Run `pytest`".
 *
 * Ported & adapted from OpenWorker `surfaces/gui/src/humanize.ts`: the model
 * does NOT emit a purpose per call (stream is name+args+result), so the
 * sentence is built here from per-tool templates. Tool names are Sage's real
 * backend tools (backend/tools/*.py) plus MCP-namespaced names
 * (`mcp__<server>__<tool>`, see backend/mcp/pool.py:namespaced_tool_name).
 */

export type ToolCallScope = 'local' | 'external';

export interface HumanizedToolCall {
  /** Action verb, present tense: "Write", "Run", "Search". */
  verb: string;
  /** Object of the action: path, command, query… Empty string when nothing salient. */
  object: string;
  /** Where the action acts. 'local' = this machine, 'external' = leaves the machine. */
  scope?: ToolCallScope;
}

type ToolArgs = Record<string, unknown>;

/** Max rendered length for the object segment — a one-liner stays one line. */
const MAX_OBJECT = 80;
/** Max rendered length for the fallback args dump (unknown tools). */
const MAX_ARGS = 96;

const trunc = (s: string, n: number): string => (s.length > n ? s.slice(0, n - 1) + '…' : s);

/** Extract a trimmed string argument, or the fallback when absent/blank. */
function strArg(args: ToolArgs, key: string, fallback = ''): string {
  const v = args[key];
  return typeof v === 'string' && v.trim() ? v.trim() : fallback;
}

/** Compact `key=value` dump for tools without a bespoke template (OpenWorker shortArgs). */
export function shortArgs(args: ToolArgs | null | undefined): string {
  if (!args || typeof args !== 'object') return '';
  return Object.entries(args)
    .map(([k, v]) => {
      let s = typeof v === 'string' ? v : (JSON.stringify(v) ?? String(v));
      if (s.length > MAX_ARGS) s = s.slice(0, MAX_ARGS - 1) + '…';
      return `${k}=${s.replace(/\n/g, ' ')}`;
    })
    .join('  ');
}

export function humanizeToolCall(
  tool: string,
  args?: ToolArgs | null,
): HumanizedToolCall {
  const a: ToolArgs = args && typeof args === 'object' ? args : {};

  switch (tool) {
    // ---- files (stay on this machine → no scope chip) ----
    case 'read_file':
      return { verb: 'Read', object: trunc(strArg(a, 'path', 'a file'), MAX_OBJECT) };
    case 'write_file':
      return {
        verb: a.append ? 'Append to' : 'Write',
        object: trunc(strArg(a, 'path', 'a file'), MAX_OBJECT),
      };
    case 'edit_file':
      return { verb: 'Edit', object: trunc(strArg(a, 'file_path', 'a file'), MAX_OBJECT) };
    case 'list_dir':
      return { verb: 'List', object: trunc(strArg(a, 'path', 'a directory'), MAX_OBJECT) };

    // ---- shell / code execution ----
    case 'bash':
    case 'terminal':
    case 'run_shell':
      return {
        verb: 'Run',
        object: trunc(strArg(a, 'command'), MAX_OBJECT) || 'a command',
        scope: 'local',
      };
    case 'bash_output':
      return {
        verb: 'Read output of',
        object: trunc(strArg(a, 'shell_id', 'a background shell'), MAX_OBJECT),
        scope: 'local',
      };
    case 'kill_shell':
      return {
        verb: 'Kill',
        object: trunc(strArg(a, 'shell_id', 'a background shell'), MAX_OBJECT),
        scope: 'local',
      };
    case 'repl': {
      const firstLine = strArg(a, 'code').split('\n')[0] ?? '';
      return {
        verb: 'Run',
        object: trunc(firstLine, MAX_OBJECT) || 'Python code',
        scope: 'local',
      };
    }

    // ---- web (leaves the machine → external) ----
    case 'web_search':
    case 'search_web':
      return { verb: 'Search', object: trunc(strArg(a, 'query'), MAX_OBJECT), scope: 'external' };
    case 'web_fetch': {
      let target = strArg(a, 'url');
      try {
        target = new URL(target).host || target;
      } catch {
        /* not a parseable URL — keep the raw string */
      }
      return { verb: 'Fetch', object: trunc(target, MAX_OBJECT), scope: 'external' };
    }

    // ---- codebase search ----
    case 'grep_search':
      return { verb: 'Search', object: trunc(strArg(a, 'pattern'), MAX_OBJECT) };
    case 'glob_search':
      return { verb: 'Find', object: trunc(strArg(a, 'pattern'), MAX_OBJECT) };

    // ---- memory ----
    case 'memory_search':
      return { verb: 'Recall', object: trunc(strArg(a, 'query'), MAX_OBJECT) };
    case 'memory_save':
      return { verb: 'Remember', object: trunc(strArg(a, 'content'), MAX_OBJECT) };

    // ---- planning / delegation / misc ----
    case 'todo_write': {
      const items = Array.isArray(a.todos)
        ? a.todos
        : Array.isArray(a.items)
          ? a.items
          : [];
      return { verb: 'Update plan', object: `${items.length} item${items.length === 1 ? '' : 's'}` };
    }
    case 'agent':
      return {
        verb: 'Delegate',
        object: trunc(strArg(a, 'description') || strArg(a, 'prompt'), MAX_OBJECT),
      };
    case 'calculator':
      return { verb: 'Calculate', object: trunc(strArg(a, 'expression'), MAX_OBJECT) };
    case 'ask_user_question':
      return { verb: 'Ask', object: trunc(strArg(a, 'question'), MAX_OBJECT) };
    case 'skill':
      return { verb: 'Use skill', object: trunc(strArg(a, 'skill', 'unknown'), MAX_OBJECT) };
    case 'office_list':
      return { verb: 'Browse office docs', object: trunc(strArg(a, 'query'), MAX_OBJECT) };
    case 'office_read':
      return { verb: 'Read office doc', object: trunc(strArg(a, 'doc_id'), MAX_OBJECT) };
    case 'structured_output':
      return { verb: 'Output', object: 'structured data' };

    default: {
      // MCP tools arrive namespaced: mcp__<server>__<tool> → "Use <server> · <tool>".
      // They act on remote services, hence the external chip.
      if (tool.startsWith('mcp__')) {
        const parts = tool.slice('mcp__'.length).split('__');
        const server = parts[0] ?? '';
        const name = parts.slice(1).join('__');
        return {
          verb: 'Use',
          object: name ? `${server} · ${name}` : server,
          scope: 'external',
        };
      }
      // Synthetic name from backend/tools/agent_tool.py for running sub-agents.
      if (tool.startsWith('subagent:')) {
        return { verb: 'Delegate', object: trunc(tool.slice('subagent:'.length).trim(), MAX_OBJECT) };
      }
      // Long tail: keep the raw name as verb, compact args as object.
      return { verb: tool, object: trunc(shortArgs(a), MAX_ARGS) };
    }
  }
}
