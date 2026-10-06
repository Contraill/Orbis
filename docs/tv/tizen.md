# Orbis on Samsung Tizen TV (Developer Mode)

Orbis for Tizen is a fullscreen launcher for the existing Orbis web frontend. The unsigned `orbis-tizen-1.0.0.wgt` is intended for a Developer Mode sideload through [Tizen Homebrew](https://github.com/SushyDev/tizen-homebrew), not Samsung Store distribution. No physical Samsung TV has yet been tested.

## Install

1. Enable Developer Mode on the TV. Follow the current Tizen Homebrew bootstrap instructions to install its launcher. Bootstrap uses your own Samsung account/certificate and target TV identity; Orbis does not bundle either.
2. On the TV/phone Tizen Homebrew interface, use its **GitHub**, **URL**, or **Upload** source to select the Orbis WGT. After public release, the intended source is the Orbis GitHub Release asset `orbis-tizen-1.0.0.wgt`. Use the Orbis 1.0.0 GitHub Release asset.
3. Tizen Homebrew must re-sign the WGT for the target TV before installation. The distributable WGT intentionally contains no personal certificate, signature or DUID. A direct unsigned WGT install outside such a re-signing flow is expected to fail signature checks.
4. Launch Orbis from the TV launcher. Enter your Orbis frontend server address. The launcher saves it locally, checks `/api/health`, and opens the existing Orbis application fullscreen.

For updates, install a newer Orbis WGT via the same Homebrew/GitHub Release flow. Tizen Homebrew is a separate TV-side installation tool; the Orbis backend does not depend on it and no Pi service is added.

The TV does not run Tailscale. A Tailscale IP works only if the TV's network/router already has a route to the tailnet/server. No address is hardcoded in the package.

If installation reports an invalid signature, use Tizen Homebrew's target-TV re-sign flow and verify Developer Mode/certificate setup. If Orbis shows **Server unavailable**, confirm the configured server address and TV-to-server reachability; select **Retry** or **Change Server**. The local launcher keeps browser chrome hidden.

The WGT config/archive was statically validated without hardware. **HARDWARE VALIDATION PENDING:** actual Homebrew installation/re-signing, launcher appearance, playback, and directional remote operation.
