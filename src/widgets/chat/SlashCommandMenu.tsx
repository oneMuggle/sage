import { clsx } from 'clsx';

import type { SlashCommand } from './slashCommands';

interface SlashCommandMenuProps {
  commands: SlashCommand[];
  selectedIndex: number;
  onSelect: (cmd: SlashCommand) => void;
}

export function SlashCommandMenu({ commands, selectedIndex, onSelect }: SlashCommandMenuProps) {
  if (commands.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 mb-1 w-64 max-h-64 overflow-y-auto bg-surface border border-border rounded-radius-md shadow-lg z-50 animate-popup-enter">
      {commands.map((cmd, i) => {
        const Icon = cmd.icon;
        return (
          <button
            key={cmd.name}
            className={clsx(
              'w-full text-left px-3 py-2 flex items-center gap-2 text-sm transition-colors',
              i === selectedIndex ? 'bg-primary/10 text-primary' : 'text-text hover:bg-bg-hover',
            )}
            onMouseDown={(e) => {
              e.preventDefault();
              onSelect(cmd);
            }}
            type="button"
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            <div>
              <div className="font-medium">/{cmd.name}</div>
              <div className="text-xs text-text-muted">{cmd.description}</div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export interface SlashCommandMenuAuditInput {
  query: string;
  matchedCommandCount: number;
  selectedIndex: number;
  isOpen: boolean;
}

export interface SlashCommandMenuAuditReport {
  normalizedQuery: string;
  matchedCommandCount: number;
  selectedIndex: number;
  selectionValid: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateSlashCommandMenuAudit(
  input: SlashCommandMenuAuditInput,
): SlashCommandMenuAuditReport {
  const normalizedQuery = input.query.trim();
  const matchedCommandCount = Math.max(0, Math.trunc(input.matchedCommandCount));
  const selectedIndex = Math.trunc(input.selectedIndex);
  const selectionValid =
    matchedCommandCount === 0
      ? selectedIndex === 0 || selectedIndex === -1
      : selectedIndex >= 0 && selectedIndex < matchedCommandCount;
  const issueCodes: string[] = [];

  if (input.isOpen && matchedCommandCount === 0) {
    issueCodes.push('no_matching_slash_commands');
  }
  if (!selectionValid) {
    issueCodes.push('slash_menu_selection_out_of_bounds');
  }

  return {
    normalizedQuery,
    matchedCommandCount,
    selectedIndex,
    selectionValid,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportSlashCommandMenuAuditJson(
  input: SlashCommandMenuAuditInput,
): string {
  return JSON.stringify(evaluateSlashCommandMenuAudit(input));
}
