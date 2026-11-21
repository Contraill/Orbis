# Changelog

## Orbis 1.1.0

- Quieter visual refresh: ink surfaces with one teal accent, self-hosted
  Archivo type, typeset Orbis name beside the orbit mark, drawn SVG icons, and a
  calmer silk background shown fully only on entry screens.
- CI publishes multi-arch backend and frontend images to GHCR; the CasaOS app
  definition in `deploy/casaos/` installs them and updates with CasaOS's Update
  button.
- TV launchers 1.1.0: the setup and offline screens follow the new look; the
  Orbis UI itself is served by the server, so TVs show the refresh as soon as
  the server is updated.

## Orbis 1.0.0

- Self-hosted catalog, localized search and profile-specific discovery for
  movies and series, with Continue Watching, My List and recommendations.
- Playback with automatic Provider → Source selection, viewer Quality/Audio/
  Subtitle controls, adaptive delivery, resume and episode lifecycle.
- Global peer-controlled Watch Together rooms with six-digit join codes and
  independently resolved media for each participant.
- Owner Admin for provider lifecycle/settings, diagnostics and sessions.
- Neutral reference provider and synthetic authoring fixtures; installation-
  specific adapters remain private runtime code.

- Developer Mode webOS and Tizen launchers; physical-TV validation remains pending.
