# Orbis on LG webOS TV (Developer Mode)

Orbis for webOS is a fullscreen launcher for your existing Orbis server, not a second streaming application. The `orbis-webos-1.0.0.ipk` package is for Developer Mode sideloading; it is not an LG Store app. A physical LG TV has **not yet been tested**.

## Install

1. Install LG's **Developer Mode** app on the TV, sign in with your own LG developer account, turn Developer Mode on, and allow the TV to reboot. Keep its session time above zero. See [LG's Developer Mode instructions](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app).
2. On the Orbis host, build the IPK with `sh tv/build-webos.sh`, or obtain `orbis-webos-1.0.0.ipk` from a future Orbis release. This uses LG's [webOS CLI `ares-package`](https://webostv.developer.lge.com/develop/tools/webos-tv-cli-dev-guide).
3. Pair the TV with the Orbis backend's bundled webOS CLI. In the Developer Mode app, turn **Key Server** on. Run:

   ```sh
   docker compose exec -e HOME=/config/tv/webos/ares-home backend ares-setup-device
   docker compose exec -e HOME=/config/tv/webos/ares-home backend ares-novacom --device livingroom --getkey
   docker compose exec -e HOME=/config/tv/webos/ares-home backend ares-device --system-info --device livingroom
   ```

   In `ares-setup-device`, create target `livingroom` using the TV's reachable IP, SSH port `9922`, and user `prisoner`. Enter the six-character passphrase shown by the TV only when `ares-novacom` asks. Keep the target/key files under `/config/tv/webos/ares-home`; never put them in Git. [LG documents this pairing sequence](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app).
4. Sideload the package with `ares-install -d livingroom orbis-webos-1.0.0.ipk` from a machine with the webOS CLI, or use a compatible Developer Mode sideload tool. If using the backend container's CLI, first copy the IPK to a mounted location such as `/config/tv/webos/`; the package itself may also be copied to any CLI machine.
5. Open Orbis on the TV. **Note the 32-character TV installation ID shown on the first setup screen before pressing Connect.** Enter the Orbis frontend address, such as `http://server:3000` or `https://orbis.example.com`. The TV saves this address locally and checks `/api/health` before opening the full Orbis UI. Register the noted ID with the Orbis backend:

   ```sh
   docker compose exec backend python -m tv.webos register <TV_INSTALLATION_ID> livingroom
   docker compose exec backend python -m tv.webos capture-token <TV_INSTALLATION_ID>
   docker compose exec backend python -m tv.webos status
   ```

The TV only sends its installation ID to Orbis. The host-side `capture-token` command reads the Developer Mode session token from the already paired TV and stores it with mode `0600` under `/config/tv/webos/tokens/`. Pairing keys and target configuration remain under `/config/tv/webos/ares-home/`. Neither token nor keys are returned by the check-in API or status command.

## Renewal and recovery

The backend attempts renewal with the current webOS CLI command `ares-launch com.palmdts.devmode -p extend=true -d livingroom`. The older `ares-extend-dev` command is only a compatibility fallback when installed. This follows [LG's current CLI guidance](https://forum.webostv.developer.lge.com/t/whats-the-way-to-extend-dev-time-with-webos-cli/28033). If app launch does not renew a compatible TV, Orbis can try LG's session-token reset endpoint. Orbis queries the remaining lifetime before and after either method and records success **only when the session actually increases into the renewed range**. A successful command or HTTP response alone is not proof.

It attempts renewal when no verified success is recorded or at least **30 days after the last verified success**. Failed or unverified attempts retry no sooner than **24 hours** later. A TV app check-in can trigger a due attempt; an in-process daily check also runs while Orbis is up. Check local state with `docker compose exec backend python -m tv.webos status`. Until tested with a paired physical TV, automatic renewal is **HARDWARE VALIDATION PENDING**; use the Developer Mode app's **EXTEND** button if necessary.

If Developer Mode's remaining session time reaches zero, [LG says it cannot be extended](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app). Orbis reports `expired_manual_recovery_required`. Re-enable Developer Mode manually on the TV, re-pair/reinstall if necessary, then run `docker compose exec backend python -m tv.webos capture-token <TV_INSTALLATION_ID>` followed by `docker compose exec backend python -m tv.webos reset <TV_INSTALLATION_ID>` to resume attempts.

Developer Mode sideload apps may be removed when Developer Mode is disabled. Updating Orbis on LG requires sideloading a newer version of the IPK. Wrapper versions track Orbis versions.

The TV does not run Tailscale. A Tailscale IP works only if the TV's network/router already has a route to that tailnet/server. Orbis never changes routing for the TV.

The package was statically built and checked without hardware. **HARDWARE VALIDATION PENDING:** real sideload, pairing, renewal, fullscreen playback, remote Back behavior, and recovery after a TV network outage.
