# Third-party notices

This inventory records **direct application dependencies** in the current
1.0.0 build. Upstream license files for the principal bundled frontend
packages and LG CLI are reproduced in `third_party_licenses/`. The frontend
lockfile records MIT, Apache-2.0, ISC, BSD-3-Clause and CC-BY-4.0 packages;
`caniuse-lite` (CC-BY-4.0) is a build-time dependency. Backend transitive
dependencies include `certifi` (MPL-2.0) and `typing_extensions` (PSF-2.0).
Container base images carry their own notices.

| Component | Version | License | Use |
| --- | --- | --- | --- |
| React / React DOM | 19.3.0 | MIT | Frontend dependency |
| React Router DOM | 7.18.4 | MIT | Frontend dependency |
| Shaka Player | 5.2.11 | Apache-2.0 | Playback dependency |
| Blobatar / @blobatar/react | 2.7.0 | MIT | Avatar dependency |
| FastAPI | 0.141.1 | MIT | Backend dependency |
| Uvicorn | 0.53.0 | BSD-3-Clause | Backend dependency |
| SQLAlchemy | 2.0.54 | MIT | Backend dependency |
| Alembic | 1.20.0 | MIT | Backend dependency |
| HTTPX | 0.28.1 | BSD-3-Clause | Backend dependency |
| pydantic-settings | 2.15.0 | MIT | Backend dependency |
| @webos-tools/cli | 3.2.6 | Apache-2.0 | LG packaging and paired-TV maintenance tooling in the backend image |

The silk background shader and glass primitives are original Orbis
implementations; no third-party demo component source is distributed here.
TMDB metadata and
optional IMDb data have separate data-use/attribution terms; see
`docs/data-attribution.md`. Runtime-fetched media artwork is not bundled in
this source tree. Orbis brand artwork was supplied for this project by the
copyright holder; it is not a third-party software dependency. No trademark
registration is claimed.
`app/frontend/tests/fixtures/player-clip.mp4` is generated from FFmpeg
`testsrc2` and a sine tone; its generation command is included beside the clip.

The unmodified `app/frontend/public/attribution/tmdb.svg` is TMDB's approved
blue square logo, credited to Travis Bell. It was retrieved from its
[Wikimedia Commons file page](https://commons.wikimedia.org/wiki/File:Tmdb.new.logo.svg),
which identifies the original TMDB asset and [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
TMDB's trademark and attribution requirements also apply. The logo is shown
below Orbis branding in the application's profile Credits/data-sources section.
