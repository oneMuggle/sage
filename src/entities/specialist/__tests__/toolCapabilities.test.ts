import { describe, expect, it } from 'vitest';

import {
  DEFAULT_SPECIALIST_PACK_IDS,
  PERMISSION_MODE_RANK,
  TOOL_CAPABILITY_PACKS,
  defaultSpecialistTools,
  describeModeGate,
  describeToolSelection,
  findToolCapabilityPack,
  highestRequiredMode,
  packSelectionState,
  togglePackInTools,
} from '../toolCapabilities';

describe('toolCapabilityPacks definitions', () => {
  it('has unique ids and non-empty tool lists', () => {
    const ids = TOOL_CAPABILITY_PACKS.map((pack) => pack.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const pack of TOOL_CAPABILITY_PACKS) {
      expect(pack.tools.length).toBeGreaterThan(0);
      expect(pack.label.length).toBeGreaterThan(0);
      expect(PERMISSION_MODE_RANK[pack.requiresMode]).toBeTypeOf('number');
    }
  });

  it('never claims the same tool in two packs', () => {
    const seen = new Map<string, string>();
    for (const pack of TOOL_CAPABILITY_PACKS) {
      for (const tool of pack.tools) {
        expect(
          seen.get(tool),
          `${tool} 同时出现在 ${seen.get(tool)} 与 ${pack.id}`,
        ).toBeUndefined();
        seen.set(tool, pack.id);
      }
    }
  });

  it('gates write and execute packs at the modes the backend enforces', () => {
    expect(findToolCapabilityPack('file-read')?.requiresMode).toBe('read_only');
    expect(findToolCapabilityPack('file-write')?.requiresMode).toBe('workspace_write');
    expect(findToolCapabilityPack('network')?.requiresMode).toBe('workspace_write');
    expect(findToolCapabilityPack('memory')?.requiresMode).toBe('workspace_write');
    expect(findToolCapabilityPack('office')?.requiresMode).toBe('workspace_write');
    expect(findToolCapabilityPack('git')?.requiresMode).toBe('workspace_write');
    expect(findToolCapabilityPack('multimodal')?.requiresMode).toBe('workspace_write');
    expect(findToolCapabilityPack('design')?.requiresMode).toBe('workspace_write');
    expect(findToolCapabilityPack('shell')?.requiresMode).toBe('full_access');
    expect(findToolCapabilityPack('browser')?.requiresMode).toBe('full_access');
    expect(findToolCapabilityPack('sage-config')?.requiresMode).toBe('full_access');
    expect(findToolCapabilityPack('schedule')?.requiresMode).toBe('full_access');
    expect(findToolCapabilityPack('skills')?.requiresMode).toBe('full_access');
    expect(findToolCapabilityPack('plugins')?.requiresMode).toBe('full_access');
  });

  it('uses the global plugin wildcard for the plugin pack', () => {
    expect(findToolCapabilityPack('plugins')?.tools).toEqual(['plugin__*']);
  });
});

describe('packSelectionState / togglePackInTools', () => {
  const readPack = findToolCapabilityPack('file-read')!;
  const writePack = findToolCapabilityPack('file-write')!;

  it('reports none / partial / all coverage', () => {
    expect(packSelectionState([], readPack)).toBe('none');
    expect(packSelectionState(['read_file'], readPack)).toBe('partial');
    expect(packSelectionState([...readPack.tools], readPack)).toBe('all');
  });

  it('adding appends only missing tools and keeps existing order', () => {
    expect(togglePackInTools(['bash'], writePack, true)).toEqual([
      'bash',
      'write_file',
      'edit_file',
      'apply_patch',
    ]);
    expect(togglePackInTools([...writePack.tools], writePack, true)).toEqual([...writePack.tools]);
  });

  it('removing drops only this pack’s tools and keeps manual entries', () => {
    const tools = ['bash', ...writePack.tools, 'office_delete', 'plugin__demo__hello'];
    expect(togglePackInTools(tools, writePack, false)).toEqual([
      'bash',
      'office_delete',
      'plugin__demo__hello',
    ]);
  });

  it('tolerates partial coverage when removing', () => {
    expect(togglePackInTools(['read_file', 'bash'], readPack, false)).toEqual(['bash']);
  });
});

describe('describeToolSelection', () => {
  it('splits fully covered, partially covered and uncategorized entries', () => {
    const fileRead = findToolCapabilityPack('file-read')!;
    const summary = describeToolSelection([
      ...fileRead.tools,
      'office_delete',
      'plugin__demo__hello',
    ]);

    expect(summary.covered.map((pack) => pack.id)).toEqual(['file-read']);
    expect(summary.partial).toEqual([]);
    expect(summary.uncategorized).toEqual(['office_delete', 'plugin__demo__hello']);
  });

  it('marks partially selected packs and empty selection as fully uncovered', () => {
    const summary = describeToolSelection(['read_file', 'office_delete']);
    expect(summary.covered).toEqual([]);
    expect(summary.partial.map((pack) => pack.id)).toEqual(['file-read']);
    expect(summary.uncategorized).toEqual(['office_delete']);
    expect(describeToolSelection([])).toEqual({ covered: [], partial: [], uncategorized: [] });
  });
});

describe('highestRequiredMode / describeModeGate', () => {
  it('returns null for an empty pack list', () => {
    expect(highestRequiredMode([])).toBeNull();
  });

  it('picks the strictest mode', () => {
    expect(
      highestRequiredMode([
        findToolCapabilityPack('file-read')!,
        findToolCapabilityPack('file-write')!,
      ]),
    ).toBe('workspace_write');
    expect(
      highestRequiredMode([
        findToolCapabilityPack('file-write')!,
        findToolCapabilityPack('shell')!,
      ]),
    ).toBe('full_access');
  });

  it('read_only allows read packs but denies write packs', () => {
    expect(describeModeGate('read_only', findToolCapabilityPack('file-read')!)).toBeNull();
    expect(describeModeGate('read_only', findToolCapabilityPack('network')!)).toMatchObject({
      level: 'deny',
    });
  });

  it('prompt downgrades denied writes to per-call approval', () => {
    expect(describeModeGate('prompt', findToolCapabilityPack('network')!)).toMatchObject({
      level: 'approval',
    });
    expect(describeModeGate('prompt', findToolCapabilityPack('shell')!)).toMatchObject({
      level: 'approval',
    });
  });

  it('workspace_write satisfies write packs but not execute packs', () => {
    expect(describeModeGate('workspace_write', findToolCapabilityPack('git')!)).toBeNull();
    expect(describeModeGate('workspace_write', findToolCapabilityPack('shell')!)).toMatchObject({
      level: 'deny',
    });
  });

  it('full_access never warns', () => {
    for (const pack of TOOL_CAPABILITY_PACKS) {
      expect(describeModeGate('full_access', pack)).toBeNull();
    }
  });
});

describe('defaultSpecialistTools', () => {
  it('expands the default packs into a deduped, non-empty tool list', () => {
    const tools = defaultSpecialistTools();
    expect(tools.length).toBeGreaterThan(0);
    expect(new Set(tools).size).toBe(tools.length);
    expect(tools).toContain('read_file');
    expect(tools).toContain('grep_search');
    expect(tools).toContain('web_fetch');
    expect(tools).toContain('memory_search');
  });

  it('derives the defaults from pack ids that all exist', () => {
    for (const id of DEFAULT_SPECIALIST_PACK_IDS) {
      expect(findToolCapabilityPack(id), `未知默认包 ${id}`).toBeDefined();
    }
    const expected = DEFAULT_SPECIALIST_PACK_IDS.flatMap(
      (id) => findToolCapabilityPack(id)?.tools ?? [],
    );
    expect(defaultSpecialistTools()).toEqual([...new Set(expected)]);
  });
});
