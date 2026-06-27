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
    <div className="absolute bottom-full left-0 mb-1 w-64 bg-surface border border-border rounded-radius-md shadow-lg overflow-hidden z-50 animate-popup-enter">
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
