#!/usr/bin/env node
// Usage: node scripts/codemod/remove-bulk-export-buttons.mjs <file...>
//
// 删除 2026-10-20~10-21 (Phase P65-P98) 批量注入的「复制MD/JSON」噪音按钮样板。
//
// 策略：按「JSX 按钮块 → useState → handler」的顺序删除，每步都以整块为单位，
// 避免留下半个函数导致语法错误。B+C 组（路径/SHA/分支/配置路径/快照/审计摘要/
// 源码/对话MD-JSON）通过 KEEP_RE 白名单保护。

import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// A 组：需要删除的文案
const DELETE_RE = new RegExp(
  [
    '复制\\s?MD',
    '复制\\s?JSON',
    '已复制MD',
    '已复制JSON',
    '已复制支柱',
    '已复制蓝图',
    '已复制管线',
    '已复制阶段',
    '已复制规范包',
    '已复制台账',
    '已复制清单',
    '已复制语境',
    '已复制全部详情',
    '已复制详情\\s?MD',
    '已复制详情\\s?JSON',
    '已复制统计\\s?JSON',
    '已复制全形态',
    '已复制项目\\s?MD',
    '已复制项目\\s?JSON',
    '已复制蓝图\\s?JSON',
    '已复制检查JSON',
    '已复制检测JSON',
    '已复制推荐里程碑',
    '已复制阶段管线',
    '已复制任务MD',
    '已复制任务JSON',
    '已复制来源JSON',
    '已复制进度JSON',
    '已复制护栏支柱',
    '已复制全部依据',
    '已复制置信度',
    '已复制预设包',
  ].join('|'),
);

// B+C 组：这些行必须保留（白名单优先）
const KEEP_RE = new RegExp(
  [
    '复制路径',
    '已复制路径',
    '复制SHA',
    '复制分支',
    '复制配置路径',
    '已复制配置路径',
    '复制快照',
    '已复制快照',
    '复制审计摘要',
    '已复制摘要',
    '复制源码',
    '已复制源码',
    '复制对话MD',
    '复制对话JSON',
    '已复制对话MD',
    '已复制对话JSON',
  ].join('|'),
);

const isDelete = (line) => DELETE_RE.test(line) && !KEEP_RE.test(line);

/** 从第 idx 行向上找到 <button 或 <span 的开标签行，返回该行索引 */
function findJsxStart(lines, idx) {
  for (let i = idx; i >= 0; i--) {
    const m = lines[i].match(/<(button|span|div|a)\b/);
    if (m) return { line: i, tag: m[1] };
  }
  return null;
}

/** 从 start 行向下找到该标签闭合，返回闭合后的行索引（含） */
function findJsxEnd(lines, start, tag) {
  const closeRe = new RegExp(`</${tag}>`);
  // 找第一个开标签闭合位置
  for (let i = start + 1; i < lines.length; i++) {
    if (closeRe.test(lines[i])) return i;
  }
  return lines.length - 1;
}

/** 删除所有含 A 组文案的 <button>/<span>/<a> JSX 块 */
function deleteJsxBlocks(source) {
  const lines = source.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    if (isDelete(lines[i])) {
      const start = findJsxStart(lines, i);
      if (start) {
        // 丢弃 out 中该块已写入的部分
        while (out.length > start.line) out.pop();
        const end = findJsxEnd(lines, start.line, start.tag);
        i = end + 1;
        continue;
      }
    }
    out.push(lines[i]);
    i++;
  }
  return out.join('\n');
}

/** 删除引用已删 state 的 handler：形如 const handleCopyXxx = ... => { ... }; */
function deleteHandlers(source) {
  const lines = source.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const m = lines[i].match(/^\s*const\s+(handleCopy\w+)\s*=/);
    if (m) {
      const name = m[1];
      // 收集整个 handler 块（含续行到顶层 `};`）
      const block = [lines[i]];
      let j = i + 1;
      let depth = (lines[i].match(/[{(]/g) || []).length - (lines[i].match(/[})]/g) || []).length;
      while (j < lines.length && depth > 0) {
        block.push(lines[j]);
        depth += (lines[j].match(/[{(]/g) || []).length - (lines[j].match(/[})]/g) || []).length;
        j++;
      }
      const text = block.join('\n');
      // handler 名里含 A 组语义（Md/Json/Markdown/Blueprint/Pillars...）且不含 B+C 语义
      const isA =
        /(Md|Json|Markdown|Blueprint|Pillars|Pipeline|Stages|BlueprintJson|AllSuite|Card|Drawer|Board|Row|Sider|Stats|Tasks|Source|Progress|Detection|Signal|Vcs|Positioning|Milestone|Preset|Guard)\w*$/.test(name) &&
        !/(Path|Sha|Branch|Config|Snapshot|AuditSummary|SourceCode|Dialog|Conversation)/.test(name);
      if (isA) {
        i = j;
        continue;
      }
      void text;
    }
    out.push(lines[i]);
    i++;
  }
  return out.join('\n');
}

/** 删除不再被引用的 copied* useState 行 */
function deleteStates(source) {
  return source
    .split('\n')
    .filter((line) => {
      const m = line.match(/const\s+\[copied(\w+),\s*setCopied\w+\]\s*=\s*useState/);
      if (!m) return true;
      const name = `copied${m[1]}`;
      // B+C 组保留
      if (/^(copiedPath|copiedConfigPath|copiedSnapshot|copiedSha|copiedBranch|copiedAudit|copiedSourceCode|copiedDialog)/.test(name))
        return true;
      // 若该 state 在本 handler/JSX 之外仍被引用（如 title 提示），保留
      // 简化判定：名字里含 A 组语义则删
      return !/(Md|Json|Markdown|Blueprint|Pillars|Pipeline|Stages|Card|Drawer|Board|Row|Sider|Stats|Tasks|Progress|Detection|Signal|Vcs|Positioning|Milestone|Preset|Guard|SelectorPath|Subtemplates|Dirs|Suite|Stats|Version|ItemId|FileJson)/.test(name);
    })
    .join('\n');
}

/** 清理未使用的 useState import + 连续空行 */
function cleanup(source) {
  let out = source.replace(/\n{3,}/g, '\n\n');
  if (!/\buseState\b/.test(out)) {
    out = out.replace(/import\s*\{\s*useState\s*\}\s*from\s*'react';\n?/g, '');
    out = out.replace(/useState,\s*/g, '');
    out = out.replace(/,\s*useState\s*/g, '');
  }
  return out;
}

function processFile(filePath) {
  const abs = resolve(filePath);
  const source = readFileSync(abs, 'utf8');
  let out = source;
  out = deleteJsxBlocks(out);
  out = deleteHandlers(out);
  out = deleteStates(out);
  out = cleanup(out);
  if (out !== source) {
    writeFileSync(abs, out);
    return true;
  }
  return false;
}

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error('Usage: node scripts/codemod/remove-bulk-export-buttons.mjs <file...>');
  process.exit(1);
}

let changed = 0;
for (const f of files) {
  if (processFile(f)) {
    console.log(`✓ ${f}`);
    changed++;
  } else {
    console.log(`- ${f} (no change)`);
  }
}
console.log(`\nProcessed ${files.length} files, changed ${changed}`);
