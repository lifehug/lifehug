# The design palette

One definition of every colour a data view uses: `system/design/palette.yaml`.
It **mirrors lifehug-platform's `architecture/design/palette.yaml` byte for
byte**, so the hosted graph and this viewer draw the same colours.

- sha256: `da772bb6fa9a29fe85c910fa7c688c726547c83aedec97d43d405f4ea2b4227e`

`tests/test_v393_design_palette.py` pins that digest, and the platform's own test
pins it on its side. Change the yaml in one repo without the other and a test
fails loudly. `system/design/palette.py` reads the yaml (standard library only,
no PyYAML) and emits the CSS custom properties (`--graph-<type>`, light under
`:root`, dark under `@media (prefers-color-scheme: dark)`); the viewer's `<style>`
carries them, and `type_color(entity_type)` returns a type's token name.

## The fixed categorical order

| Slot | Type | Hue | Light | Dark | Token |
|---|---|---|---|---|---|
| 1 | `person` | orange | `#ad620c` | `#bd7634` | `--graph-person` |
| 2 | `place` | violet | `#8160b5` | `#9e80d1` | `--graph-place` |
| 3 | `period` | green | `#478638` | `#69a45c` | `--graph-period` |
| 4 | `object` | rose | `#9f4d86` | `#b2659a` | `--graph-object` |
| 5 | `theme` | olive | `#98870c` | `#97871d` | `--graph-theme` |
| 6 | `project` | cyan | `#0887aa` | `#0095b5` | `--graph-project` |
| 7 | `event` | red | `#b14d51` | `#c46668` | `--graph-event` |
| 8 | `self` | blue | `#3f6db9` | `#6995df` | `--graph-self` |
| 9 | `lifes_work` | teal | `#0c9a78` | `#0d9675` | `--graph-lifes-work` |

The viewer's wiki directories are plural (`people`, `themes`, ...); they map to
the singular palette types. `life` (the hub) shares `self`; a relationship wears
the amber edge token `--graph-relationship`. An unknown type draws
`--graph-fallback` and logs a warning; it is never given a colour.

**The order is the colour-blind-safety mechanism.** Never re-order, never cycle
past nine. Hue is never the only channel: every node is direct-labelled and the
legend under the picture pairs each present type's swatch with its name.

## What the viewer does with it

- Nodes, edges and the legend wear the tokens; no type colour literal lives in
  the graph page.
- Selection is a ring: 2 px at radius+4 in the node's type colour, neighbours
  1 px, keyboard focus the same ring. There is no rectangular outline.
- Fit / Reset / Full screen use the platform's paper `.control` style in the
  canvas's top-right corner at 44 px (twin of `controls.module.css`).
- The graph canvas, list and text follow `prefers-color-scheme: dark`.

## How to add a colour

Edit the yaml in **lifehug-platform** first (new types go at the END of `order`
with the next slot, with `oklch_light` / `oklch_dark`, re-validated for both
modes), copy it here verbatim, update the digest in this page and in the test,
and map any new viewer directory in `VIEWER_TYPE_ALIASES`.

🤖 Generated with Claude Sonnet 5.5 via Claude Code
