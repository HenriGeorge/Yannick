#!/usr/bin/env node
// capture.mjs — design-import capture stage
//
// Resolves an input into a single `captured.html` (fully-rendered DOM + inline CSS)
// plus an asset manifest. Handles three input classes:
//
//   1. http(s) URL           → fetch() (static) or Playwright (--render=playwright|auto)
//   2. file:// or local path  → readFile  (NEW — closes gap 1 from the handoff)
//   3. "bundled export" HTML  → decode the inlined <script type="__bundler/template">
//                               (NEW — these files have NO rendered DOM until JS runs,
//                                but the rendered HTML is already embedded as JSON, so
//                                Playwright is unnecessary and would just re-run the bundle)
//
// Usage:
//   node capture.mjs <url|path> [--render=static|playwright|auto] [--out=DIR]
//
// Fails loudly: clear message + non-zero exit, never silent empty output.

import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve, isAbsolute } from 'node:path';

const args = process.argv.slice(2);
if (args.length === 0) die('No input given. Pass a URL or local file path.');

const input = args[0];
const flags = Object.fromEntries(
  args.slice(1)
    .filter(a => a.startsWith('--'))
    .map(a => { const [k, v = true] = a.replace(/^--/, '').split('='); return [k, v]; })
);
const render = flags.render || 'static';
const outDir = resolve(flags.out || 'captured');

function die(msg) { console.error(`\n[capture] ERROR: ${msg}\n`); process.exit(1); }
function note(msg) { console.error(`[capture] ${msg}`); }

// ── classify the input ──────────────────────────────────────────────────────
function classify(inp) {
  if (/^https?:\/\//i.test(inp)) return 'http';
  if (/^file:\/\//i.test(inp)) return 'file';
  // bare path, absolute or relative
  return 'file';
}

function toLocalPath(inp) {
  if (/^file:\/\//i.test(inp)) return fileURLToPath(inp);
  return isAbsolute(inp) ? inp : resolve(process.cwd(), inp);
}

// ── detect the "bundled export" wrapper ─────────────────────────────────────
// These files ship a thumbnail + a gzipped JS bundle, with the *rendered* HTML
// stored verbatim (JSON-encoded) inside <script type="__bundler/template">.
function extractBundledTemplate(html) {
  const m = html.match(/<script type="__bundler\/template">([\s\S]*?)<\/script>/);
  if (!m) return null;
  try {
    const decoded = JSON.parse(m[1].trim()); // it's a JSON string literal
    return typeof decoded === 'string' ? decoded : null;
  } catch (e) {
    note(`found __bundler/template but could not JSON-decode it: ${e.message}`);
    return null;
  }
}

// ── http capture (unchanged behaviour, summarised) ──────────────────────────
async function captureHttp(url) {
  if (render === 'playwright' || render === 'auto') {
    let chromium;
    try { ({ chromium } = await import('playwright')); }
    catch {
      if (render === 'playwright')
        die('--render=playwright but playwright is not installed.\n  Run: npm i -D playwright && npx playwright install chromium');
      note('playwright unavailable; falling back to static fetch (--render=auto)');
    }
    if (chromium) {
      const browser = await chromium.launch();
      const page = await browser.newPage();
      await page.goto(url, { waitUntil: 'networkidle' });
      const html = await page.content();
      await browser.close();
      return html;
    }
  }
  const res = await fetch(url);
  if (!res.ok) die(`fetch ${url} → HTTP ${res.status}`);
  return await res.text();
}

// ── file capture (NEW) ──────────────────────────────────────────────────────
async function captureFile(inp) {
  const path = toLocalPath(inp);
  if (!existsSync(path)) die(`local file not found: ${path}`);
  let html = await readFile(path, 'utf-8');

  const tpl = extractBundledTemplate(html);
  if (tpl) {
    note('detected bundled-export wrapper → using inlined rendered template');
    note('(Playwright not needed: rendered DOM is already embedded)');
    return tpl;
  }
  // ordinary local HTML file — return as-is.
  // (A real JS-driven SPA saved locally would need --render=playwright against a
  //  served copy; we warn rather than silently capturing an empty shell.)
  if (/<div id="__bundler_thumbnail"|requires JavaScript/i.test(html) && !tpl) {
    note('WARNING: file looks JS-driven but no inlined template found.');
    note('  Serve it (npx serve DIR) and capture the localhost URL with --render=playwright.');
  }
  return html;
}

// ── run ─────────────────────────────────────────────────────────────────────
const kind = classify(input);
note(`input classified as: ${kind}`);
const html = kind === 'http' ? await captureHttp(input) : await captureFile(input);

if (!html || html.trim().length < 50) die('captured HTML is empty — refusing to write.');

await mkdir(outDir, { recursive: true });
await writeFile(resolve(outDir, 'captured.html'), html, 'utf-8');

// minimal asset manifest: note any url(...) refs (fonts/images) for follow-up
const assets = [...new Set([...html.matchAll(/url\((["']?)([^"')]+)\1\)/g)].map(m => m[2]))]
  .filter(u => !u.startsWith('data:'));
await writeFile(resolve(outDir, 'assets.json'), JSON.stringify(assets, null, 2));

note(`wrote ${outDir}/captured.html (${html.length} chars)`);
note(`wrote ${outDir}/assets.json (${assets.length} asset refs)`);
