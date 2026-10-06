# Orbis visual system · silk and glass

The product shell uses the supplied artwork in `app/frontend/public/brand/`:
`wordmark.png` in wide navigation, setup and profile selection;
`standalone-icon.png` in compact navigation and favicon contexts; and
`app-icon.png` for the manifest, touch icon and CasaOS icon URL.

## Procedural silk

`OrbisSilkBackground.tsx` contains the product's own WebGL2 fragment shader:
layered value-noise folds, a flowing horizon, narrow vertical ribs, cyan/teal
ridge light, dark valleys and subtle grain. No third-party demo shader or
component source is bundled.

One canvas persists across consumer routes. The renderer caps device pixel
ratio at 1.5 and resolution at 1920×1080, draws at most about 25 frames/s,
stops when the document is hidden or the player route is active, and draws a
single static frame for reduced-motion users. Context failure uses a dark CSS
fallback. Browse pages lower the canvas opacity, while profile/setup and
search show it more clearly. Detail imagery remains dominant and no silk is
painted over playback.

## Glass surfaces

The navigation, search, account menu, tabs, toggles and panels use shared
Orbis glass tokens and product components. No external component collection,
demo copy, imagery, Tailwind or animation dependency is imported.

`silk-glass.css` defines semantic navy, glass, text, accent, focus, shadow,
blur and radius tokens. Blur is limited to the floating nav, menus, search,
setup/profile panels and a few supporting controls; poster artwork remains
unblurred. Semi-transparent dark surfaces remain legible if backdrop-filter is
unavailable. Pointer and keyboard focus use the same Orbis cyan/teal palette.

## CasaOS

`x-casaos.icon` and the frontend container's `icon` label use the distributable
Orbis app icon. A private installation may override them in an ignored local
Compose override to use its own reachable frontend origin. CasaOS-managed apps
use the metadata; CasaOS also reads the label on Docker containers. This does not change Docker or
host networking. The stack was originally started outside CasaOS, so CasaOS
may still require an authenticated dashboard refresh/import to create a
managed app tile; adding an icon never changes container ownership.
