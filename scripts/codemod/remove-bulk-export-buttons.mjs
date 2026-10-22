#!/usr/bin/env node
// Usage:
//   node scripts/codemod/remove-bulk-export-buttons.mjs <file...>          # apply edits
//   node scripts/codemod/remove-bulk-export-buttons.mjs --check <file...>  # residual gate (exit 1 if any A-group element remains)
//   node scripts/codemod/remove-bulk-export-buttons.mjs --report <file...> # dump classify verdicts as TSV
//
// 删除 2026-10-20~10-21 (Phase P13-P98) 批量注入的「复制MD/JSON」噪音按钮样板。
//
// 策略：TS Compiler API (ts.createSourceFile + TSX) 识别 JSX 元素 → 4 信号
// 提取 (children text/literals + title + aria-label) → 有序规则分类
// (KEEP_C → DELETE(MD|JSON) → KEEP_B → DELETE(A名词) → KEEP) → 字符区间
// 删除 (含条件包装 `{cond && <button/>}` 与整行缩进/换行) → 死代码清扫
// (标识符出现次数=1 → 删除声明，fixpoint) → ts.transpileModule 自检
// (语法错误 → 中止不写) → 收尾 (空行折叠 + 未用 useState import 清理)。

import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ts = require('typescript');

// ---- 分类规则 ----
const KEEP_C = ['复制审计摘要', '复制源码', '复制对话 MD', '复制对话 JSON', '复制对话MD', '复制对话JSON'];
const KEEP_B = ['复制路径', '复制 SHA', '复制SHA', '复制分支', '复制配置路径', '复制快照'];
const A_NOUN = [
  '蓝图', '支柱', '管线', '阶段', '规范包', '台账', '清单', '语境', '全部依据', '置信度',
  '预设包', '护栏重点', '里程碑', '统计', '分布', '全部详情', '全形态', '详情',
];

function norm(arr) {
  return arr.map((x) => x.replace(/^✓\s*/, '').replace(/\s+/g, ' ').trim()).filter(Boolean);
}

function verdict(sig) {
  const j = sig.join(' ');
  for (const k of KEEP_C) if (j.includes(k)) return { v: 'KEEP_C', why: k };
  if (/\bMD\b|Markdown/.test(j)) return { v: 'DELETE', why: 'MD' };
  if (/\bJSON\b/.test(j)) return { v: 'DELETE', why: 'JSON' };
  for (const k of KEEP_B) if (j.includes(k)) return { v: 'KEEP_B', why: k };
  for (const k of A_NOUN) if (j.includes(k)) return { v: 'DELETE', why: `A:${k}` };
  return { v: 'KEEP', why: 'no-marker' };
}

// ---- 信号提取 ----
function litTexts(node) {
  const out = [];
  const walk = (n) => {
    if (!n) return;
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) { out.push(n.text); return; }
    if (ts.isConditionalExpression(n)) { walk(n.whenTrue); walk(n.whenFalse); return; }
    if (ts.isParenthesizedExpression(n)) { walk(n.expression); return; }
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.PlusToken) { walk(n.left); walk(n.right); return; }
  };
  walk(node);
  return out;
}

function signals(el) {
  const s = new Set();
  for (const child of el.children) {
    if (ts.isJsxText(child)) {
      const t = child.text.replace(/\s+/g, ' ').trim();
      if (t) s.add(t);
    } else if (ts.isJsxExpression(child) && child.expression) {
      for (const l of litTexts(child.expression)) s.add(l);
    }
  }
  for (const attr of el.openingElement.attributes.properties) {
    if (!ts.isJsxAttribute(attr)) continue;
    if (attr.name.text !== 'title' && attr.name.text !== 'aria-label') continue;
    if (attr.initializer && ts.isStringLiteral(attr.initializer)) s.add(attr.initializer.text);
  }
  return [...s];
}

// ---- 找出应该被整体删除的节点 ----
// `{cond && (<button/>)}`  → 删整个 JsxExpression
// `{cond && <button/>}`     → 删整个 JsxExpression
// `{cond ? <button/> : null}` → 删整个 JsxExpression
// 孤立的 `<button/>`         → 只删该元素
function findDeletionTarget(node) {
  let cur = node;
  for (let guard = 0; guard < 12; guard++) {
    const parent = cur.parent;
    if (!parent) break;

    // 跳过括号
    if (ts.isParenthesizedExpression(parent)) { cur = parent; continue; }

    // {cond && (...)} / {cond && <el/>}
    if (ts.isBinaryExpression(parent) && parent.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
      if (parent.right === cur) {
        const wrapper = parent.parent;
        if (wrapper && ts.isJsxExpression(wrapper)) return wrapper;
        // `{cond && ...}` 出现在 JSX children 位置但不是 JsxExpression（罕见）→ 只删元素
        return cur;
      }
      return cur;
    }

    // {cond ? <el/> : null}
    if (ts.isConditionalExpression(parent)) {
      const other = parent.whenTrue === cur ? parent.whenFalse : parent.whenTrue;
      if (other.kind === ts.SyntaxKind.NullKeyword || other.kind === ts.SyntaxKind.FalseKeyword) {
        const wrapper = parent.parent;
        if (wrapper && ts.isJsxExpression(wrapper)) return wrapper;
      }
      return cur;
    }

    // 塌缩只含该元素的包裹元素（避免留下空壳）
    if (ts.isJsxElement(parent) && !ts.isReturnStatement(parent.parent)) {
      const meaningful = parent.children.filter(
        (c) => !(ts.isJsxText(c) && c.text.trim() === ''),
      );
      if (meaningful.length === 1 && meaningful[0] === cur) { cur = parent; continue; }
    }

    return cur;
  }
  return cur;
}

// ---- Phase 1: 分类 → 字符区间 ----
function classify(source, fileName) {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const targets = []; // {start, end, why}

  const visit = (node) => {
    if (ts.isJsxElement(node)) {
      const tag = node.openingElement.tagName.getText(sf);
      if (tag === 'button' || tag === 'span' || tag === 'a') {
        const sig = norm(signals(node));
        if (sig.some((s) => s.includes('复制'))) {
          const vd = verdict(sig);
          if (vd.v === 'DELETE') {
            const delNode = findDeletionTarget(node);
            let start = delNode.getStart(sf);
            let end = delNode.getEnd();
            // 向前吃缩进 (同行的前导空白)
            while (start > 0 && (source[start - 1] === ' ' || source[start - 1] === '\t')) start--;
            // 向后吃一个换行 (包括 \r\n)
            if (source[end] === '\r') end++;
            if (source[end] === '\n') end++;
            targets.push({ start, end, why: vd.why, sig: sig.join(' | ') });
          }
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return targets;
}

// ---- 应用字符区间删除 ----
function applyEdits(source, edits) {
  if (edits.length === 0) return source;
  // 合并重叠区间
  edits.sort((a, b) => a.start - b.start);
  const merged = [edits[0]];
  for (let i = 1; i < edits.length; i++) {
    const last = merged[merged.length - 1];
    if (edits[i].start <= last.end) last.end = Math.max(last.end, edits[i].end);
    else merged.push(edits[i]);
  }
  // 倒序切片
  let out = source;
  for (let i = merged.length - 1; i >= 0; i--) {
    out = out.slice(0, merged[i].start) + out.slice(merged[i].end);
  }
  return out;
}

// ---- Phase 2: 死代码清扫 ----
// 标识符出现次数 == 1 (仅其声明处) → 删除该声明语句
// 重复直到 fixpoint

function countIdentifiers(source, name) {
  // 简单正则：作为独立标识符出现 (前后是非 \w 或行首尾)
  const re = new RegExp(`\\b${name}\\b`, 'g');
  const m = source.match(re);
  return m ? m.length : 0;
}

function findStatementRange(source, name) {
  // 找到 `const name = ...` 或 `const [..., name, ...] = ...` 所在语句，返回 [start, end) 含换行
  const lines = source.split('\n');
  let startLine = -1;
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(new RegExp(`\\b(const|let|var)\\s+.*\\b${name}\\b`));
    if (m) { startLine = i; break; }
  }
  if (startLine < 0) return null;
  // 向下找语句结尾：深度归零 + 遇到 ; 或行尾
  let depth = 0;
  let endLine = startLine;
  for (let i = startLine; i < lines.length; i++) {
    const line = lines[i];
    for (const ch of line) {
      if (ch === '{' || ch === '(' || ch === '[') depth++;
      else if (ch === '}' || ch === ')' || ch === ']') depth--;
    }
    if (depth === 0 && /;\s*$/.test(line)) { endLine = i; break; }
    if (depth === 0 && i > startLine && lines[i].trim() === '') { endLine = i - 1; break; }
    endLine = i;
  }
  // 计算字符区间 (含整行)
  let start = 0;
  for (let i = 0; i < startLine; i++) start += lines[i].length + 1;
  let end = 0;
  for (let i = 0; i <= endLine; i++) end += lines[i].length + 1;
  return { start, end };
}

function sweepDeadCode(source) {
  let prev;
  do {
    prev = source;
    // useState: const [x, setX] = useState(...)
    const useStates = [...source.matchAll(/const\s+\[(\w+),\s*(\w+)\]\s*=\s*useState/g)];
    for (const m of useStates) {
      const [x, setX] = [m[1], m[2]];
      if (countIdentifiers(source, x) <= 1 && countIdentifiers(source, setX) <= 1) {
        const r = findStatementRange(source, x);
        if (r) {
          source = source.slice(0, r.start) + source.slice(r.end);
          continue;
        }
      }
    }
    // handler: const handleFoo = () => { ... };  或  const handleFoo = useCallback(...);
    const handlers = [...source.matchAll(/^\s*const\s+(handle\w+)\s*=/gm)];
    for (const m of handlers) {
      const name = m[1];
      if (countIdentifiers(source, name) <= 1) {
        const r = findStatementRange(source, name);
        if (r) {
          source = source.slice(0, r.start) + source.slice(r.end);
          continue;
        }
      }
    }
  } while (source !== prev);
  return source;
}

// ---- Phase 3: 收尾 ----
function cleanup(source) {
  // 折叠 3+ 空行 → 2
  source = source.replace(/\n{3,}/g, '\n\n');
  // 若 useState 完全没被使用 → 从 import 移除
  if (!/\buseState\b/.test(source)) {
    source = source.replace(/import\s*\{\s*useState\s*\}\s*from\s*'react';\s*\n?/g, '');
    source = source.replace(/useState,\s*/g, '');
    source = source.replace(/,\s*useState\s*/g, '');
    // 处理 import React, { useState, useEffect } from 'react'; 情况
    source = source.replace(/\{\s*\}\s*from\s*'react'/g, () => {
      // 若 import 列表空了，整行删
      return '';
    });
    source = source.replace(/import\s*\{\s*\}\s*from\s*'react';\s*\n?/g, '');
  }
  return source;
}

// ---- 自检 ----
function selfCheck(source) {
  const result = ts.transpileModule(source, {
    reportDiagnostics: true,
    compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.Latest },
  });
  const diags = result.diagnostics || [];
  if (diags.length > 0) {
    const msg = diags
      .map((d) => {
        const pos = d.start != null ? source.slice(0, d.start).split('\n').length : 0;
        return `  L${pos}: ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`;
      })
      .join('\n');
    console.error(msg);
  }
  return diags.length === 0;
}

// ---- 主流程 ----
function processFile(filePath, mode) {
  const abs = resolve(filePath);
  const source = readFileSync(abs, 'utf8');

  const targets = classify(source, filePath);

  if (mode === 'report') {
    for (const t of targets) {
      console.log([filePath, t.why, t.sig].join('\t'));
    }
    return { changed: false, targets: targets.length };
  }

  if (mode === 'check') {
    return { changed: false, targets: targets.length };
  }

  // mode === 'apply'
  if (targets.length === 0) return { changed: false, targets: 0 };

  let out = applyEdits(source, targets);
  out = sweepDeadCode(out);
  out = cleanup(out);

  if (!selfCheck(out)) {
    console.error(`✗ ${filePath}: self-check failed, skipping write`);
    return { changed: false, targets: targets.length, broken: true };
  }

  if (out !== source) {
    writeFileSync(abs, out);
    return { changed: true, targets: targets.length };
  }
  return { changed: false, targets: targets.length };
}

const args = process.argv.slice(2);
let mode = 'apply';
if (args[0] === '--check') { mode = 'check'; args.shift(); }
else if (args[0] === '--report') { mode = 'report'; args.shift(); }

if (args.length === 0) {
  console.error('Usage:');
  console.error('  node scripts/codemod/remove-bulk-export-buttons.mjs <file...>');
  console.error('  node scripts/codemod/remove-bulk-export-buttons.mjs --check <file...>');
  console.error('  node scripts/codemod/remove-bulk-export-buttons.mjs --report <file...>');
  process.exit(2);
}

let changed = 0;
let broken = 0;
let totalTargets = 0;
for (const f of args) {
  const r = processFile(f, mode);
  totalTargets += r.targets;
  if (mode === 'apply') {
    if (r.changed) { console.log(`✓ ${f}`); changed++; }
    else if (r.broken) broken++;
    else console.log(`- ${f} (no change)`);
  }
}

if (mode === 'check') {
  if (totalTargets > 0) {
    console.error(`✗ ${totalTargets} residual A-group elements in ${args.length} files`);
    process.exit(1);
  }
  console.log(`✓ no residual A-group elements`);
} else if (mode === 'apply') {
  console.log(`\nProcessed ${args.length} files, changed ${changed}, broken ${broken}, removed ${totalTargets} elements`);
  if (broken > 0) process.exit(1);
}
