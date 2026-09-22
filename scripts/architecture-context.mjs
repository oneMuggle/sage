#!/usr/bin/env node

import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';

const policy = JSON.parse(readFileSync('architecture-policy.json', 'utf-8'));
const moduleId = process.argv[2];

if (!moduleId) {
  console.error('Usage: node scripts/architecture-context.mjs <module-id>');
  process.exit(1);
}

const module = policy.modules.find(m => m.id === moduleId);
if (!module) {
  console.error(`Module '${moduleId}' not found`);
  process.exit(1);
}

console.log(`Module: ${module.id}`);
console.log(`Roots: ${module.roots.join(', ')}`);
if (module.requires) {
  console.log(`Requires: ${module.requires.join(', ')}`);
}

console.log('Public entrypoints:');
for (const root of module.roots) {
  const files = readdirSync(root).filter(f => f.endsWith('.ts') || f.endsWith('.tsx') || f.endsWith('.py'));
  for (const file of files.slice(0, 5)) {
    console.log(`  - ${join(root, file)}`);
  }
}
