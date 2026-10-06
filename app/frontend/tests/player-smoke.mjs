// Final Player UI contract smoke. Every API and media byte is intercepted; never touches private playback state.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH ?? "playwright-core");
if (process.env.ORBIS_PLAYER_FIXTURE !== "1" || !["http://127.0.0.1", "http://media-app-frontend"].includes(process.env.APP_URL)) throw new Error("Explicit isolated player fixture required");
const clip = readFileSync(new URL("./fixtures/player-clip.mp4", import.meta.url));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? "/usr/bin/chromium", args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const profile = { id: 1, name: "Test Viewer", avatar: null, avatar_seed: "test", locale: "en-US", is_owner: true, preferred_audio_language: "en", preferred_subtitle_language: "en", subtitles_enabled: false, autoplay_next_episode: true, trailer_muted: true, onboarding_seeds: [] };
const client = { id: "fixture-client", profile_id: 1, display_name: "Fixture browser", client_type: "web", state: "paused", capabilities: null, last_seen: "2026-01-01T00:00:00Z", current_playback: null, position_seconds: 0, revoked_at: null };
let episode = 1;
let preferredQuality = null;
let preferredSource = null;
const requests = [];
const playback = () => ({
  client_session_id: client.id, source_session_id: `fixture-source-${episode}`, source_expires_at: null, source_expiry_status: "healthy", refresh_at: null,
  choices: { providers: [{ provider_id: "fixture", label: "Fixture" }], sources: [{ source_id: "local", label: "Local source" }], qualities: [{ height: 720, label: "720p" }], selected_quality_height: preferredQuality, max_compatible_height: 1080, quality_outcome: preferredQuality ? "selected" : "auto" },
  state: { profile_id: 1, media_type: "tv", tmdb_id: 50, season_number: 1, episode_number: episode, position_seconds: 0, duration_seconds: 4, resume_position_seconds: 0, completed: false, last_provider_id: "fixture", preferred_provider_id: null, preferred_source_provider_id: preferredSource ? "fixture" : null, preferred_source_id: preferredSource, preferred_quality_height: preferredQuality, preferred_audio_language: "en", preferred_audio_kind: "original", subtitles_enabled: true, preferred_subtitle_language: "en", updated_at: "2026-01-01T00:00:00Z" },
  resolution: { selected_provider_id: "fixture", attempts: [] },
  selected_source: { source_id: "local", source_label: "Local source", provider_id: "fixture", url: "http://127.0.0.1/player-fixture.mp4", protocol: "http", quality: "720p", audio_tracks: [{ language: "en", label: "English", kind: "original", track_id: "audio-en" }], subtitle_tracks: [{ language: "en", label: "English", kind: "external", url: "http://media-app-frontend/player-fixture.vtt", format: "vtt", track_id: "subs-en", forced: false }], expires_at: null },
  selected_audio: { track: { language: "en", label: "English", kind: "original", track_id: "audio-en" }, matched_by: "profile" },
  selected_subtitles: { enabled: true, can_disable: true, selected_track: { language: "en", label: "English", kind: "external", url: "http://media-app-frontend/player-fixture.vtt", format: "vtt", track_id: "subs-en", forced: false }, burned_in_track: null },
});
const response = (route, data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
await page.addInitScript(({ client }) => { localStorage.setItem("media-app.selected-profile.v1", "1"); sessionStorage.setItem("orbis.client-session", JSON.stringify(client)); }, { client });
await page.route("**/player-fixture.mp4", route => route.fulfill({ status: 200, contentType: "video/mp4", body: clip, headers: { "Accept-Ranges": "bytes" } }));
await page.route("**/player-fixture.vtt", route => route.fulfill({ status: 200, contentType: "text/vtt", body: "WEBVTT\n\n00:00:00.000 --> 00:00:04.000\nFixture subtitle\n", headers: { "Access-Control-Allow-Origin": "*" } }));
await page.route("**/api/**", async route => {
  const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
  if (path === "/api/profiles") return response(route, [profile]);
  if (path === "/api/setup") return response(route, { locale: "en-US", setup_required: false, owner_id: 1, owner_password_configured: true });
  if (path === `/api/sessions/${client.id}`) return response(route, client);
  if (path === "/api/catalog/tv/50") return response(route, { tmdb_id: 50, media_type: "tv", title: "Fixture Series", original_title: "Fixture Series", overview: "Fixture", poster_url: null, backdrop_url: null, release_date: null, vote_average: null, credits: [], production_companies: [], videos: [], seasons: [{ tmdb_id: 500, season_number: 1, name: "Season 1", episode_count: 2, poster_url: null }], related: [], external_ids: {}, genres: [], runtime_minutes: null, status: null, number_of_seasons: 1, number_of_episodes: 2 });
  if (path === "/api/catalog/tv/50/season/1") return response(route, { series_tmdb_id: 50, season_tmdb_id: 500, season_number: 1, name: "Season 1", overview: "", air_date: null, poster_url: null, episodes: [1,2].map(n => ({ episode_number: n, name: `Fixture episode ${n}`, overview: "", air_date: null, still_url: null, runtime_minutes: null, vote_average: null })) });
  if (path === "/api/playback/profiles/1/states") return response(route, []);
  if (path.endsWith("/lifecycle")) return response(route, { current: { tmdb_id: 50, season_number: 1, episode_number: episode, title: `Fixture episode ${episode}`, aired: true }, previous: episode === 1 ? null : { tmdb_id: 50, season_number: 1, episode_number: 1, title: "Fixture episode 1", aired: true }, next: episode === 1 ? { tmdb_id: 50, season_number: 1, episode_number: 2, title: "Fixture episode 2", aired: true } : null, next_status: episode === 1 ? "available" : "final", season_transition: false, is_final_episode: episode === 2, autoplay_next: true, autoplay_allowed: episode === 1, resume_position_seconds: 0, markers: {}, marker_source: null, warning: null });
  if (path.endsWith("/state") && method === "PUT") return response(route, { ...playback().state, ...route.request().postDataJSON() });
  if (path.endsWith("/choices")) { const data = route.request().postDataJSON(); requests.push(data); preferredQuality = data.preferred_quality_height ?? null; preferredSource = data.preferred_source_id ?? null; return response(route, playback()); }
  if (path.endsWith("/transition")) { episode = 2; return response(route, playback()); }
  if (path.endsWith("/prepare-next")) return response(route, { ...playback(), preparation_only: true });
  if (path.endsWith("/resolve") || path.endsWith("/refresh") || path.endsWith("/recover") || path.endsWith("/failover")) return response(route, playback());
  return response(route, { error: { code: "fixture_missing", message: "Fixture route missing" } }, 404);
});
try {
  await page.goto(process.env.APP_URL + "/watch/1/tv/50/season/1/episode/1");
  await page.getByRole("main", { name: "Video player" }).waitFor();
  await page.waitForFunction(() => document.querySelector("video.media-player")?.readyState >= 2);
  await page.locator("video.media-player").evaluate(video => { video.loop = true; });
  if (await page.locator("video.media-player").evaluate(video => video.paused)) await page.getByRole("button", { name: "Play", exact: true }).click();
  await page.waitForFunction(() => {
    const video = document.querySelector("video.media-player");
    const cue = video?.textTracks[0]?.activeCues?.[0];
    return cue && "line" in cue && cue.line === 68 && cue.snapToLines === false;
  }, null, { timeout: 8000 });
  await page.screenshot({ path: join(tmpdir(), "orbis-player-smoke-subtitles.png") });
  assert.equal(await page.locator("video.media-player").evaluate(video => video.hasAttribute("controls")), false);
  await page.locator("video.media-player").evaluate(video => {
    const old = video.currentTime;
    Object.defineProperty(video, "currentTime", { configurable: true, get: () => old, set: value => { video.dataset.qaTarget = String(value); } });
  });
  const slider = page.getByRole("slider", { name: "Seek position" });
  await slider.evaluate(input => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, "2.5");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.waitForFunction(() => document.querySelector("video.media-player")?.dataset.qaTarget === "2.5");
  await page.locator("video.media-player").evaluate(video => video.dispatchEvent(new Event("timeupdate")));
  assert.equal(Number(await slider.inputValue()), 2.5, "Stale timeupdate moved pending seek target");
  await page.locator(".orbital-loading-overlay").waitFor();
  await page.locator("video.media-player").evaluate(video => { const target = Number(video.dataset.qaTarget); delete video.currentTime; video.currentTime = target; });
  await page.waitForFunction(() => !document.querySelector("video.media-player")?.dataset.orbisPendingSeek, null, { timeout: 8000 });
  await page.locator(".orbital-loading-overlay").waitFor({ state: "hidden" });
  await page.waitForFunction(() => document.querySelector(".orbis-player")?.classList.contains("controls-hidden"), null, { timeout: 6500 });
  await page.mouse.move(100, 120);
  await page.waitForFunction(() => document.querySelector(".orbis-player")?.classList.contains("controls-visible"));
  assert.equal(await page.getByRole("button", { name: "Provider", exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "Source", exact: true }).count(), 0);
  await page.waitForTimeout(3400);
  await page.mouse.move(150, 140);
  await page.locator("video.media-player").evaluate(video => video.dispatchEvent(new Event("waiting")));
  await page.locator(".orbital-loading-overlay").waitFor();
  await page.locator("video.media-player").evaluate(video => video.dispatchEvent(new Event("canplay")));
  await page.locator(".orbital-loading-overlay").waitFor({ state: "hidden" });
  await page.getByRole("button", { name: "Quality", exact: true }).click();
  await page.getByRole("button", { name: "720p" }).click();
  assert.equal(requests.at(-1)?.preferred_quality_height, 720);
  await page.getByRole("button", { name: "Audio", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "English" }).count(), 1);
  await page.getByRole("button", { name: "Subtitles", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Off" }).count(), 1);
  await page.getByRole("button", { name: "Episodes", exact: true }).click();
  await page.getByRole("button", { name: /Fixture episode 2/ }).waitFor();
  await page.getByRole("button", { name: /Fixture episode 2/ }).click();
  await page.waitForURL("**/watch/1/tv/50/season/1/episode/2");
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
  await page.getByRole("button", { name: "Quality", exact: true }).click();
  const boxes = await page.evaluate(() => ({ menu: document.querySelector(".orbis-player-menu").getBoundingClientRect().bottom, bottom: document.querySelector(".orbis-player-bottom").getBoundingClientRect().top }));
  assert.ok(boxes.menu <= boxes.bottom, `Mobile menu overlaps controls: ${JSON.stringify(boxes)}`);
  await page.keyboard.press("Escape");
  assert.equal(new URL(page.url()).pathname, "/watch/1/tv/50/season/1/episode/2");
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  await page.keyboard.press("Escape");
  await page.waitForURL("**/tv/50?season=1");
  assert.deepEqual(errors, []);
  console.log("PASS final player: consumer choices, buffering loader, episode navigation, Escape hierarchy, mobile sheet and no native controls");
} finally { await browser.close(); }
