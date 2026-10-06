// capture.mjs — capture a live page (or one element) → a SHARP vector SVG via dom-to-svg
// (generalized from page-to-svg). The ONLY subcommand family whose deps are heavy — playwright,
// esbuild, dom-to-svg — so they are LAZY `await import()`ed inside run() and wrapped: a missing dep
// surfaces the npm-install hint, NEVER a raw MODULE_NOT_FOUND stack (the R5 zero-dep-core invariant —
// no static capture-dep import here or in any core lib; see tests/test_figma_toolkit.sh FT2/FT2b/FT3).
//   --url=<url>                 page to capture (required)
//   --out=<file.svg>            output path (required)
//   --selector=<css>            capture one element instead of the whole document
//   --strip-images              replace <img>/canvas/bg-images with neutral placeholders (layout kept)
//   --strip-selectors=<csv>     remove these selectors before capture (dev overlays etc.; project-set)
//   --detect-error-boundary     opt-in: fail if a React/Next error boundary was captured
//   --viewport-width=<px>       default 1440   ·   --max-height=<px>  truncate + disclose past this
//   --min-text=<n>              min <text> nodes for a capture to count as real (default 5). Lower
//                               (e.g. 1) for legitimately low-text visual components (color canvas,
//                               swatch, spinner, dropzone) that the default floor false-rejects.
// Node core only at load time; the capture deps load on first run().
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { execFileSync } from "node:child_process";

// The one place the optional deps enter. Any resolution failure → the install hint (not a stack).
const INSTALL_HINT =
  "capture needs playwright + esbuild + dom-to-svg (optional deps). Install them with:\n" +
  "  npm install --prefix plugins/claude-template-core/skills/figma-bridge/scripts/figma";

export async function loadCaptureDeps() {
  try {
    const [{ chromium }, esbuild] = await Promise.all([import("playwright"), import("esbuild")]);
    await import("dom-to-svg"); // presence gate — the actual bundling is via esbuild below
    return { chromium, esbuild };
  } catch (err) {
    const code = err?.code;
    const msg = err?.message ?? String(err);
    if (code === "ERR_MODULE_NOT_FOUND" || /Cannot find (package|module)/i.test(msg)) {
      throw new Error(INSTALL_HINT);
    }
    throw err;
  }
}

function parseFlags(args) {
  const flags = {};
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) flags[m[1]] = m[2];
    else if (a.startsWith("--")) flags[a.slice(2)] = true;
  }
  return flags;
}

// Bundle dom-to-svg into a browser IIFE hung off window.domToSvg (esbuild resolves dom-to-svg here).
async function buildDomToSvgIIFE(esbuild) {
  const out = await esbuild.build({
    stdin: {
      // double-quoted specifier on purpose: keeps this string off FT2b's single-quoted static-import
      // grep (the real import is the lazy await import() in loadCaptureDeps; this is browser-bundle src).
      contents:
        'import { elementToSVG, documentToSVG, inlineResources } from "dom-to-svg";\n' +
        "window.domToSvg = { elementToSVG, documentToSVG, inlineResources };",
      resolveDir: dirname(new URL(import.meta.url).pathname),
      loader: "js",
    },
    bundle: true,
    format: "iife",
    platform: "browser",
    write: false,
  });
  return out.outputFiles[0].text;
}

// XML 1.0 forbids most C0 control chars (except \t \n \r) — strip them so the SVG parses.
function stripBadXmlChars(s) {
  // eslint-disable-next-line no-control-regex
  return s.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
}

const NEXT_ERROR_MARKER_RE = /aria-owns="__next_error__"/;
export function detectErrorBoundary(svg) {
  return NEXT_ERROR_MARKER_RE.test(svg);
}

// A real production page renders far more than a handful of text runs; a near-empty capture is a
// rasterized/unpainted/error page, not the design. Cheap always-on floor.
export const MIN_REAL_TEXT_COUNT = 5;

// PURE truncation-disclosure decision (extracted so it is unit-testable without a browser).
export function computeTruncationDisclosure(heightBeforeCap, maxHeight) {
  if (maxHeight == null || heightBeforeCap <= maxHeight) {
    return { shouldCap: false, truncated: false, originalHeight: null };
  }
  return { shouldCap: true, truncated: true, originalHeight: Math.round(heightBeforeCap) };
}

// SSRF guard: fetching a captured-page <image> URL server-side reaches hosts the browser's own SOP
// refused. Block loopback / link-local / RFC-1918 / IPv6 ULA so a page embedding e.g.
// http://169.254.169.254/… or http://localhost:PORT/… can't turn capture into an internal-fetch +
// exfil-to-Figma primitive. Literal-IP + localhost only (DNS-rebinding is out of scope for a dev tool).
export function isInternalHost(hostname) {
  const h = String(hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
  if (!h || h === "localhost" || h.endsWith(".localhost") || h === "::1" || h === "0.0.0.0") return true;
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.\d{1,3}$/.exec(h);
  if (m) {
    const a = Number(m[1]), b = Number(m[2]);
    if (a === 0 || a === 127 || a === 10) return true;
    if (a === 169 && b === 254) return true; // link-local incl. 169.254.169.254 cloud metadata
    if (a === 192 && b === 168) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
  }
  // IPv6 ULA / link-local, unspecified, and IPv4-mapped (`::ffff:169.254.169.254` → `::ffff:a9fe:a9fe`;
  // WHATWG keeps the `::ffff:` prefix) — the last would otherwise reach loopback/metadata unblocked.
  if (h === "::" || h.startsWith("::ffff:") || h.startsWith("fc") || h.startsWith("fd") || h.startsWith("fe80")) return true;
  return false;
}

// Replace cross-origin <image href="http…"> with curl-fetched base64 data URIs (CORS blocks the
// in-browser inliner). Scoped to <image> tags only (never <a> hrefs). OFF by default (opt-in via
// `inlineRemote`) — see the SSRF guard above. Returns the rewritten SVG.
function inlineRemoteImages(svg) {
  return svg.replace(/<image\b[^>]*>/g, (imageTag) =>
    imageTag.replace(/(xlink:href|href)="(https?:\/\/[^"]+)"/, (whole, attr, url) => {
      let host;
      try {
        host = new URL(url).hostname;
      } catch {
        return whole;
      }
      if (isInternalHost(host)) {
        console.error(`  ! SSRF guard: refusing to inline remote image from internal host ${host}: ${url}`);
        return whole;
      }
      try {
        // No -L: a public URL that 30x-redirects to an internal host must not be followed.
        const buf = execFileSync("curl", ["-fsS", "--max-time", "20", url], {
          maxBuffer: 64 * 1024 * 1024,
        });
        let mime = "image/png";
        const ext = url.split("?")[0].split(".").pop().toLowerCase();
        if (ext === "jpg" || ext === "jpeg") mime = "image/jpeg";
        else if (ext === "webp") mime = "image/webp";
        else if (ext === "gif") mime = "image/gif";
        else if (ext === "svg") mime = "image/svg+xml";
        return `${attr}="data:${mime};base64,${buf.toString("base64")}"`;
      } catch (e) {
        console.error(`  ! could not inline remote image ${url}: ${e.message}`);
        return whole;
      }
    }),
  );
}

// In-page DOM prep run before serialization. Project-agnostic: canvas→img, un-fix scrollers, and
// remove any caller-supplied `stripSelectors` (dev overlays etc. — no hardcoded Next.js/review-dock).
const PRE_CAPTURE_FIX = (stripSelectors) => {
  for (const c of Array.from(document.querySelectorAll("canvas"))) {
    try {
      const url = c.toDataURL("image/png");
      const img = document.createElement("img");
      img.src = url;
      const r = c.getBoundingClientRect();
      img.width = r.width;
      img.height = r.height;
      img.style.cssText = c.style.cssText;
      img.className = c.className;
      c.replaceWith(img);
    } catch {
      /* tainted/empty canvas — skip */
    }
  }
  for (const sel of stripSelectors) {
    for (const el of Array.from(document.querySelectorAll(sel))) el.remove();
  }
  for (const el of Array.from(document.querySelectorAll("*"))) {
    const cs = getComputedStyle(el);
    if (cs.position === "fixed") el.style.position = "static";
    if (/(auto|scroll)/.test(cs.overflowY) && el !== document.body) {
      el.style.overflow = "visible";
      el.style.maxHeight = "none";
      el.style.height = "auto";
    }
  }
};

// Replace each <img>/canvas/bg-image with a neutral same-box placeholder (layout preserved exactly).
const STRIP_IMAGES = () => {
  const PLACEHOLDER = "#9ca3af"; // neutral mid-gray, theme-agnostic
  for (const img of Array.from(document.querySelectorAll("img"))) {
    const cs = getComputedStyle(img);
    const r = img.getBoundingClientRect();
    const div = document.createElement("div");
    div.setAttribute("data-figma-capture-placeholder", "img");
    div.style.cssText = img.style.cssText;
    div.className = img.className;
    div.style.display = cs.display === "inline" ? "inline-block" : cs.display;
    div.style.width = `${r.width}px`;
    div.style.height = `${r.height}px`;
    div.style.background = PLACEHOLDER;
    div.style.borderRadius = cs.borderRadius;
    div.style.flexShrink = cs.flexShrink;
    img.replaceWith(div);
  }
  for (const c of Array.from(document.querySelectorAll("canvas"))) {
    const r = c.getBoundingClientRect();
    const div = document.createElement("div");
    div.style.cssText = c.style.cssText;
    div.style.width = `${r.width}px`;
    div.style.height = `${r.height}px`;
    div.style.background = PLACEHOLDER;
    div.className = c.className;
    c.replaceWith(div);
  }
  for (const el of Array.from(document.querySelectorAll("*"))) {
    const cs = getComputedStyle(el);
    if (cs.backgroundImage && cs.backgroundImage !== "none") {
      el.style.backgroundImage = "none";
      el.style.backgroundColor = PLACEHOLDER;
    }
  }
};

// Truncate the DOM past maxHeight (documentToSVG serializes the whole tree regardless of viewport).
const CAP_HEIGHT_FIX = (maxHeight) => {
  function walk(node) {
    for (const child of Array.from(node.children)) {
      if (getComputedStyle(child).position === "fixed") continue;
      const r = child.getBoundingClientRect();
      if (r.top >= maxHeight) child.remove();
      else if (r.bottom > maxHeight) walk(child);
    }
  }
  walk(document.body);
};

function validateXml(svg) {
  const trimmed = svg.trim();
  if (!/<svg[\s>]/i.test(trimmed.slice(0, 200)) && !trimmed.startsWith("<svg")) {
    throw new Error("SVG does not start with an <svg> root");
  }
  if (!/<\/svg>\s*$/i.test(trimmed)) throw new Error("SVG does not end with </svg>");
  const badAmp = trimmed.match(/&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/);
  if (badAmp) {
    throw new Error(
      "SVG contains an unescaped ampersand near: " +
        trimmed.slice(Math.max(0, badAmp.index - 20), badAmp.index + 20),
    );
  }
}

/**
 * capture(opts, deps) — deps = { chromium, esbuild } from loadCaptureDeps(). Returns
 * { outSvg, textCount, bytes, height, truncated, originalHeight }.
 */
export async function capture(
  {
    url,
    outSvg,
    selector,
    viewportWidth = 1440,
    stripImages = false,
    stripSelectors = [],
    detectErrorBoundary: detectEB = false,
    maxHeight = null,
    inlineRemote = false,
    minText = MIN_REAL_TEXT_COUNT,
  },
  { chromium, esbuild },
) {
  const iife = await buildDomToSvgIIFE(esbuild);
  const browser = await chromium.launch();
  const context = await browser.newContext({
    deviceScaleFactor: 2,
    reducedMotion: "reduce",
    viewport: { width: viewportWidth, height: 1200 },
  });
  const page = await context.newPage();
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForTimeout(400);
    await page.evaluate(PRE_CAPTURE_FIX, stripSelectors);
    await page.waitForTimeout(200);

    const preStripHeight = await page.evaluate(() =>
      Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
    );
    await page.setViewportSize({
      width: viewportWidth,
      height: Math.min(Math.ceil(preStripHeight) + 40, 20000),
    });
    await page.waitForTimeout(stripImages ? 800 : 200);

    if (stripImages) {
      await page.evaluate(STRIP_IMAGES);
      await page.waitForTimeout(200);
      const postStripHeight = await page.evaluate(() =>
        Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
      );
      if (postStripHeight > preStripHeight) {
        await page.setViewportSize({
          width: viewportWidth,
          height: Math.min(Math.ceil(postStripHeight) + 40, 20000),
        });
        await page.waitForTimeout(200);
      }
    }

    let truncated = false;
    let originalHeight = null;
    if (maxHeight != null) {
      const heightBeforeCap = await page.evaluate(() =>
        Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
      );
      const decision = computeTruncationDisclosure(heightBeforeCap, maxHeight);
      if (decision.shouldCap) {
        await page.evaluate(CAP_HEIGHT_FIX, maxHeight);
        await page.waitForTimeout(150);
        const heightAfterCap = await page.evaluate(() =>
          Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
        );
        await page.setViewportSize({ width: viewportWidth, height: Math.ceil(heightAfterCap) + 40 });
        await page.waitForTimeout(150);
        truncated = decision.truncated;
        originalHeight = decision.originalHeight;
        console.log(
          `[capture] capped height ${Math.round(heightBeforeCap)}px -> ${Math.round(heightAfterCap)}px (maxHeight=${maxHeight}) for ${outSvg}`,
        );
      }
    }

    await page.addScriptTag({ content: iife });
    const rawSvg = await page.evaluate(async (sel) => {
      const target = sel ? document.querySelector(sel) : null;
      if (sel && !target) return { error: `selector not found: ${sel}` };
      const svgDoc = sel
        ? window.domToSvg.elementToSVG(target)
        : window.domToSvg.documentToSVG(document);
      try {
        await window.domToSvg.inlineResources(svgDoc.documentElement);
      } catch {
        /* best-effort inlining; remote images handled below */
      }
      return { svg: new XMLSerializer().serializeToString(svgDoc) };
    }, selector);
    if (rawSvg.error) throw new Error(rawSvg.error);

    let svg = stripBadXmlChars(rawSvg.svg);
    if (inlineRemote) svg = inlineRemoteImages(svg); // opt-in: server-side fetch of remote images (SSRF-guarded)
    validateXml(svg);
    const textCount = (svg.match(/<text[\s>]/g) || []).length;
    const bytes = Buffer.byteLength(svg, "utf8");

    if (detectEB && detectErrorBoundary(svg)) {
      throw new Error(
        `captured an error boundary (aria-owns="__next_error__"), not the real page — ${url}`,
      );
    }
    if (textCount < minText) {
      throw new Error(
        `only ${textCount} <text> node(s) (< ${minText}) — looks rasterized or unpainted, not a real capture of ${url}`,
      );
    }

    mkdirSync(dirname(outSvg), { recursive: true });
    writeFileSync(outSvg, svg, "utf8");
    const heightMatch = /<svg[^>]*\sheight="([\d.]+)"/.exec(svg);
    const height = heightMatch ? Number(heightMatch[1]) : null;
    console.log(
      `[capture] WROTE ${outSvg}  <text>=${textCount}  bytes=${bytes}${truncated ? `  TRUNCATED ${originalHeight}px->${Math.round(height ?? 0)}px` : ""}`,
    );
    return { outSvg, textCount, bytes, height, truncated, originalHeight };
  } finally {
    await browser.close();
  }
}

export async function run(args) {
  // Validate args BEFORE the dep gate so a bad flag fails fast with a clear message (not the install
  // hint, and not a silently-skipped sanity gate). `--min-text` is `!== undefined` (not truthy) so
  // `--min-text=0` is honored; a non-numeric or negative value must ERROR, never coerce to NaN/neg and
  // silently disable the real-capture floor (`textCount < NaN` is always false).
  const flags = parseFlags(args);
  const url = flags.url;
  const outSvg = flags.out;
  if (!url || !outSvg) throw new Error("capture: --url=<url> and --out=<file.svg> are required");
  const minText = flags["min-text"] !== undefined ? Number(flags["min-text"]) : MIN_REAL_TEXT_COUNT;
  if (!Number.isFinite(minText) || minText < 0) {
    throw new Error(`capture: --min-text must be a non-negative number, got "${flags["min-text"]}"`);
  }
  const deps = await loadCaptureDeps(); // lazy dep gate — a missing dep → the install hint
  await capture(
    {
      url,
      outSvg,
      selector: typeof flags.selector === "string" ? flags.selector : undefined,
      viewportWidth: flags["viewport-width"] ? Number(flags["viewport-width"]) : 1440,
      stripImages: Boolean(flags["strip-images"]),
      stripSelectors:
        typeof flags["strip-selectors"] === "string"
          ? flags["strip-selectors"].split(",").map((s) => s.trim()).filter(Boolean)
          : [],
      detectErrorBoundary: Boolean(flags["detect-error-boundary"]),
      maxHeight: flags["max-height"] ? Number(flags["max-height"]) : null,
      inlineRemote: Boolean(flags["inline-remote-images"]),
      minText,
    },
    deps,
  );
}
