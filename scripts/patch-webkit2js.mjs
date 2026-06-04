#!/usr/bin/env node
/**
 * Patch node_modules to work around WebKitGTK 4.0 (libwebkit2gtk-4.0-37) JSC
 * missing lookbehind (?<=...) and Unicode property escapes (\p{P} \p{S}).
 *
 * Affects:
 *   - mdast-util-gfm-autolink-literal (used by react-markdown + remark-gfm)
 *   - .vite/deps/remark-gfm.js (Vite pre-bundled cache; regenerated on build)
 *
 * Why: Sage targets Windows 7 (Tauri 1.6 + webkit2gtk-sys 0.18, which only
 * supports webkit2gtk-4.0). The 4.0 JSC engine predates ES2018 regex
 * extensions, so any Markdown render that loads these files throws
 * "SyntaxError: Invalid regular expression: invalid group specifier name".
 *
 * Strategy: drop Unicode property escapes from the email detector. Falls back
 * to ASCII boundary chars + start-of-string. Misses some CJK punctuation
 * edge cases but unblocks the entire chat render pipeline.
 *
 * Re-run:  node scripts/patch-webkit2js.mjs
 * Auto-runs: package.json "postinstall"
 */

import { readFile, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')

const PATCHES = [
  {
    file: 'node_modules/mdast-util-gfm-autolink-literal/lib/index.js',
    // (?<=^|\s|\p{P}|\p{S}) -> (?<=^|\s|[!-/:-@\[-`{-~])
    // Keep lookbehind (some JSCs handle it), but replace \p{P}|\p{S}
    // with the ASCII PUNCT class they roughly correspond to.
    from: '(?<=^|\\s|\\p{P}|\\p{S})',
    to: '(?<=^|\\s|[!-/:-@\\[-`{-~])',
  },
]

let patched = 0
let failed = 0

for (const { file, from, to } of PATCHES) {
  const abs = path.join(ROOT, file)
  if (!existsSync(abs)) {
    console.warn(`  skip (not installed): ${file}`)
    continue
  }
  try {
    const before = await readFile(abs, 'utf8')
    if (!before.includes(from)) {
      console.log(`  ok (already patched): ${file}`)
      continue
    }
    const after = before.replaceAll(from, to)
    await writeFile(abs, after, 'utf8')
    console.log(`  patched: ${file}`)
    patched++
  } catch (err) {
    console.error(`  FAIL: ${file} - ${err.message}`)
    failed++
  }
}

// Also clean Vite's pre-bundled cache so remark-gfm gets re-bundled with
// the patched source. Next `npm run dev` or `npm run build` will rebuild it.
const viteCache = path.join(ROOT, 'node_modules/.vite/deps/remark-gfm.js')
if (existsSync(viteCache)) {
  try {
    const before = await readFile(viteCache, 'utf8')
    if (before.includes('(?<=^|\\s|\\p{P}|\\p{S})')) {
      const after = before.replaceAll(
        '(?<=^|\\s|\\p{P}|\\p{S})',
        '(?<=^|\\s|[!-/:-@\\[-`{-~])',
      )
      await writeFile(viteCache, after, 'utf8')
      console.log('  patched: node_modules/.vite/deps/remark-gfm.js (cache)')
      patched++
    } else {
      console.log('  ok (vite cache already clean): remark-gfm.js')
    }
  } catch (err) {
    console.error(`  FAIL: vite cache - ${err.message}`)
    failed++
  }
}

console.log('')
console.log(`patch-webkit2js: ${patched} patched, ${failed} failed`)
if (failed > 0) process.exit(1)
