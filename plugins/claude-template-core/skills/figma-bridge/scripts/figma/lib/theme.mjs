// theme.mjs — token sets for light/dark + auto luminance derivation from a captured background.
// Pure, zero-dep. site-build reads cfg.theme and the capture manifest's sampleBg, then threads
// the returned tokens into frame style defaults.

export const TOKENS = {
  light: { cardBg: '#ffffff', border: '#e5e5e5', text: '#111111' },
  dark:  { cardBg: '#1e1e1e', border: '#3a3a3a', text: '#f5f5f5' },
}

/**
 * Relative luminance (WCAG) of a #rrggbb hex, 0..1. Unknown/invalid input → 1 (treated as light).
 * @param {string} hex
 * @returns {number}
 */
export function luminance(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '')
  if (!m) return 1
  const [r, g, b] = [m[1], m[2], m[3]].map(h => parseInt(h, 16) / 255)
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

/**
 * Resolve a token set. 'light'/'dark' return the fixed set; 'auto' picks dark when the sample
 * background is dark (luminance < 0.5), else light. No sample → light (safe default).
 * @param {'light'|'dark'|'auto'} mode
 * @param {string} [sampleBgHex]
 * @returns {{cardBg:string,border:string,text:string}}
 */
export function themeFor(mode, sampleBgHex) {
  if (mode === 'light' || mode === 'dark') return TOKENS[mode]
  return luminance(sampleBgHex) < 0.5 ? TOKENS.dark : TOKENS.light
}
