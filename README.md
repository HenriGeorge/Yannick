# Yannick Henderickx — Sonic Portfolio

A dark, cinematic single-page portfolio for **Yannick Henderickx** (a.k.a. *jeanre*) — composer, sound designer & audio director.

The site lives inside the light of Yannick's portrait: a film gradient that fades from a bright sage/mauve haze at the top into deep plum as you scroll, with floating dots, film grain, a cursor-following glow and a custom cursor.

All audio is **synthesized live in the browser** with the Web Audio API — nothing is loaded:

- An ambient drone that starts bright/open at the top and closes its filter as you scroll into the dark.
- Four distinct generative "tracks" for the project players (Halos, Pulse // Field, Monolith, Aether).
- Pentatonic mouse-tones that respond to cursor movement across the whole site, and a touchable sound playground.

Visuals are drawn with Canvas 2D: an audio-reactive oscilloscope hero field, generative project thumbnails, the particle playground, atmosphere dots, grain, and live meters that track the playing track's spectrum.

## Stack

Vanilla HTML / CSS / JavaScript — no build step, no dependencies (just Google Fonts). Recreated from a Claude Design prototype as a self-contained static site.

```
index.html        markup
css/styles.css     palette, type, layout, hover/active/focus states
js/main.js         interactive engine (cursor, canvas, Web Audio, state)
assets/yannick.jpg editorial portrait
```

## Run locally

```bash
python3 -m http.server 8765
# open http://localhost:8765
```

Sound needs a click (browser autoplay rule) — hit **ENABLE SOUND** or any **PLAY** button.

## Notes

- Honors `prefers-reduced-motion` (animations/transitions disabled) and hides the custom cursor on touch devices.
- The four projects, clients and testimonials are placeholders from the design; the contact email (`hello@jeanre.studio`) is a placeholder. Swap in real content when available.
