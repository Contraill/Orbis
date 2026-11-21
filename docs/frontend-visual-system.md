# Orbis visual system

Dark ink surfaces, one teal accent from the orbit mark, and the silk background
as the single atmospheric element. Posters and backdrops carry the colour; the
interface stays quiet around them.

## Brand

`BrandMark` (`src/app/BrandMark.tsx`) pairs the orbit mark
(`public/brand/mark.png`, a trimmed copy of `standalone-icon.png`) with the name
set in Archivo at its widest width, echoing the extended capitals of the original
wordmark. On phones the header shows the mark alone. `app-icon.png` remains the
manifest, touch and CasaOS icon; `wordmark.png` is kept for the TV launcher shell.

## Type

Archivo (SIL OFL 1.1) is self-hosted from `public/fonts/` as one variable font
with weight and width axes, split into Latin and Latin Extended subsets so
Turkish characters are covered. The latin subset is preloaded from `index.html`.
Headings use weight 700 with slight negative tracking; interface text uses 400–600.

## Colour and surfaces

`src/product.css` defines the tokens: `--bg` ink, three solid surface steps,
neutral hairlines, three text levels (all at least 4.5:1 on every surface) and a
single `--accent`. The accent is reserved for the primary action, the active nav
underline, progress, selection and focus. Surfaces are solid; there is no glass
or glow in the product UI. Older token names (`--glass-*`, `--text-primary`,
`--accent-primary`, …) are kept as aliases for `style.css`, `player.css` and
admin.

Over video the player keeps translucent, blurred panels because they must stay
legible above moving pictures.

## Silk

`OrbisSilkBackground.tsx` is the product's own WebGL2 fragment shader: a soft
ribbon of satin folds that run along the curve, in the teal-to-blue of the orbit
mark, drifting slowly. One canvas persists across routes. It is shown fully on
entry screens (profile picker, setup, add profile, taste selection), at half
strength on browse pages, faintly on detail and admin, and is hidden on the
player. The renderer caps device pixel ratio at 1.5 and resolution at 1920×1080,
draws at most about 25 frames/s, stops when the document is hidden, and draws a
single static frame for reduced-motion users. Context failure falls back to a
CSS gradient.

Home and detail artwork fade into the silk through a bottom mask rather than
ending on a hard edge. The header is a gradient scrim that fills in as the page
scrolls (scroll-driven animation, with the gradient as the fallback).

## Icons

`src/app/Icon.tsx` holds the interface icons as 24px stroke SVGs in one weight.
No Unicode glyphs stand in for icons.

## CasaOS

`x-casaos.icon` in `deploy/casaos/Apps/orbis/docker-compose.yml` uses the distributable app
icon. A private installation may point it at its own reachable frontend origin.
