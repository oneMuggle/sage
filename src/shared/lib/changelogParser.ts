/**
 * Changelog parser utility
 * Parses CHANGELOG.md format and categorizes changes by type
 */

export interface ChangelogEntry {
  version: string;
  date: string;
  highlights: {
    major: string[]; // feat: or ### Added
    improvements: string[]; // perf:, refactor:, or ### Changed
    fixes: string[]; // fix: or ### Fixed
  };
  raw: string;
}

/**
 * Parse CHANGELOG.md content into structured entries
 */
export function parseChangelog(markdown: string): ChangelogEntry[] {
  const entries: ChangelogEntry[] = [];

  // Split by version headers: ## [vX.Y.Z] - YYYY-MM-DD or ## [Unreleased]
  const versionRegex = /## \[([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})/g;
  const matches = Array.from(markdown.matchAll(versionRegex));

  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    const version = match[1];
    const date = match[2];
    const startIndex = match.index! + match[0].length;
    const endIndex = i + 1 < matches.length ? matches[i + 1].index! : markdown.length;
    const content = markdown.slice(startIndex, endIndex);

    const highlights = extractHighlights(content);

    entries.push({
      version,
      date,
      highlights,
      raw: content.trim(),
    });
  }

  return entries;
}

/**
 * Extract categorized highlights from version content
 */
function extractHighlights(content: string): ChangelogEntry['highlights'] {
  const highlights: ChangelogEntry['highlights'] = {
    major: [],
    improvements: [],
    fixes: [],
  };

  // Extract ### Added section
  const addedSection = extractSection(content, 'Added');
  if (addedSection) {
    highlights.major.push(...parseBulletPoints(addedSection));
  }

  // Extract ### Changed section
  const changedSection = extractSection(content, 'Changed');
  if (changedSection) {
    highlights.improvements.push(...parseBulletPoints(changedSection));
  }

  // Extract ### Fixed section
  const fixedSection = extractSection(content, 'Fixed');
  if (fixedSection) {
    highlights.fixes.push(...parseBulletPoints(fixedSection));
  }

  // Also look for conventional commit prefixes in any section
  const lines = content.split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('-')) continue;

    const text = trimmed.slice(1).trim();

    // feat: prefix
    if (text.match(/^feat(\(.+\))?:/i)) {
      const item = text.replace(/^feat(\(.+\))?:/i, '').trim();
      if (!highlights.major.includes(item)) {
        highlights.major.push(item);
      }
    }

    // perf:, refactor:, chore: prefixes
    if (text.match(/^(perf|refactor|chore)(\(.+\))?:/i)) {
      const item = text.replace(/^(perf|refactor|chore)(\(.+\))?:/i, '').trim();
      if (!highlights.improvements.includes(item)) {
        highlights.improvements.push(item);
      }
    }

    // fix: prefix
    if (text.match(/^fix(\(.+\))?:/i)) {
      const item = text.replace(/^fix(\(.+\))?:/i, '').trim();
      if (!highlights.fixes.includes(item)) {
        highlights.fixes.push(item);
      }
    }
  }

  return highlights;
}

/**
 * Extract a specific section (### SectionName) from content
 */
function extractSection(content: string, sectionName: string): string | null {
  const sectionRegex = new RegExp(`### ${sectionName}([\\s\\S]*?)(?=###|$)`, 'i');
  const match = content.match(sectionRegex);
  return match ? match[1].trim() : null;
}

/**
 * Parse bullet points from a section
 */
function parseBulletPoints(section: string): string[] {
  const items: string[] = [];
  const lines = section.split('\n');

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('-') || trimmed.startsWith('*')) {
      const text = trimmed.slice(1).trim();
      if (text) {
        items.push(text);
      }
    }
  }

  return items;
}

/**
 * Generate summary from changelog entries
 */
export function generateSummary(entries: ChangelogEntry[]): {
  currentVersion: ChangelogEntry | null;
  recentVersions: ChangelogEntry[];
  highlightsByCategory: {
    major: string[];
    improvements: string[];
    fixes: string[];
  };
} {
  if (entries.length === 0) {
    return {
      currentVersion: null,
      recentVersions: [],
      highlightsByCategory: { major: [], improvements: [], fixes: [] },
    };
  }

  const currentVersion = entries[0];
  const recentVersions = entries.slice(1, 4); // Next 3 versions

  // Aggregate highlights from current version
  const highlightsByCategory = {
    major: currentVersion.highlights.major,
    improvements: currentVersion.highlights.improvements,
    fixes: currentVersion.highlights.fixes,
  };

  return { currentVersion, recentVersions, highlightsByCategory };
}
