// Targeted, isolated Watch Together UI test. All API/media responses are fixtures.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH ?? "playwright-core");
if (process.env.ORBIS_WATCH_FIXTURE !== "1" || !["http://media-app-frontend", "http://172.19.0.1:3000"].includes(process.env.APP_URL)) throw new Error("Explicit isolated fixture required");
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? "/usr/bin/chromium", args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const profiles = [1, 2].map(id => ({ id, name: id === 1 ? "Can" : "Zey", avatar: null, avatar_seed: `seed-${id}`, avatar_config: null, locale: "en-US", is_owner: id === 1, preferred_audio_language: null, preferred_subtitle_language: null, subtitles_enabled: false, autoplay_next_episode: true, trailer_muted: true, onboarding_seeds: [] }));
const room = { type: "state", room_id: "opaque-internal-fixture", join_code: "482731", revision: 1, content_revision: 0, content: null, content_key: null, host_id: "p1", status: "closed", state: "paused", position: 0, rate: 1, participants: [] };
const sockets = new Map(), transitions = [], playCommands = [], errors = [];
const member = id => `p${id}`;
const broadcast = () => { for (const ws of sockets.values()) ws.send(JSON.stringify(room)); };
const json = (route, data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
const contexts = [], pages = [];
try {
 for (const id of [1, 2]) {
  const context = await browser.newContext({ viewport: id === 2 ? { width: 390, height: 844 } : { width: 1280, height: 800 } });
  contexts.push(context);
  await context.addInitScript(({ id }) => {
   localStorage.setItem("media-app.selected-profile.v1", String(id));
   sessionStorage.setItem("orbis.client-session", JSON.stringify({ id: `fixture-client-${id}`, profile_id: id, display_name: "Fixture", client_type: "web" }));
   Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
   document.execCommand = command => { window.__copiedText = command === "copy" ? document.activeElement.value : null; return command === "copy"; };
  }, { id });
  await context.route("**/api/**", route => {
   const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
   const sid = route.request().headers()["x-orbis-session"], caller = sid?.endsWith("1") ? 1 : 2;
   if (path === "/api/setup") return json(route, { locale: "en-US", setup_required: false, owner_id: 1, owner_password_configured: true });
   if (path === "/api/profiles") return json(route, profiles);
   if (path.startsWith("/api/sessions/")) return json(route, { id: path.split("/").at(-1), profile_id: id, display_name: "Fixture", client_type: "web", state: "paused" });
   if (path === `/api/feeds/profiles/${id}/home`) return json(route, { surface: "home", personalized: false, shelves: [], next_cursor: null });
   if (path.includes("/continue") || path.endsWith("/states")) return json(route, []);
   if (path === "/api/catalog/unified-search") return json(route, { results: [{ key: "tv:50", kind: "tv", media_type: "tv", tmdb_id: 50, title: "Fixture Series", poster_url: null, release_date: "2026-01-01", roles: [] }], next_cursor: null });
   if (path === "/api/catalog/tv/50") return json(route, { tmdb_id: 50, media_type: "tv", title: "Fixture Series", original_title: "Fixture Series", overview: "Fixture", poster_url: null, backdrop_url: null, release_date: null, vote_average: null, credits: [], production_companies: [], videos: [], related: [], seasons: [{ season_number: 1, episode_count: 1, name: "Season 1" }], genres: [], number_of_seasons: 1 });
   if (path === "/api/catalog/tv/50/season/1") return json(route, { series_tmdb_id: 50, season_number: 1, episodes: [{ episode_number: 1, name: "Pilot", overview: "", air_date: null, still_url: null }] });
   if (path === "/api/catalog/tv/50/ratings") return json(route, { ratings: [] });
   if (path === "/api/watch-together/rooms" && method === "POST") { room.status = "open"; room.revision++; room.content = null; room.content_key = null; room.content_revision = 0; room.host_id = member(id); room.participants = [{ id: member(id), profile_id: id, name: profiles[id - 1].name, connected: false, ready: false }]; return json(route, { ...room, participant_id: member(id) }, 201); }
   if (path === "/api/watch-together/join" && method === "POST") { assert.equal(route.request().postDataJSON().join_code, room.join_code); assert.equal(room.status, "open"); if (!room.participants.some(p => p.id === member(id))) room.participants.push({ id: member(id), profile_id: id, name: profiles[id - 1].name, connected: false, ready: false }); room.revision++; broadcast(); return json(route, { ...room, participant_id: member(id) }); }
   if (path === `/api/watch-together/rooms/${room.room_id}` && method === "GET") return json(route, { ...room, participant_id: member(id) });
   if (path.endsWith("/transition") && method === "POST") { const data = route.request().postDataJSON(); assert.equal(data.revision, room.revision); transitions.push(caller); room.revision++; room.content_revision = room.revision; room.content = data.content; room.content_key = `tv:${data.content.tmdb_id}:s${data.content.season_number}:e${data.content.episode_number}`; broadcast(); return json(route, room); }
   if (path.endsWith("/exit") && method === "POST") { room.participants = room.participants.filter(p => p.id !== member(caller)); room.revision++; if (!room.participants.length) room.status = "closed"; broadcast(); return json(route, { status: room.status === "closed" ? "closed" : "left" }); }
   return json(route, { detail: { code: "fixture_missing" } }, 404);
  });
  await context.routeWebSocket(`**/api/watch-together/rooms/${room.room_id}/ws`, ws => {
   let who = "";
   ws.onMessage(message => { const data = JSON.parse(message); if (data.session_id) { who = member(data.session_id.endsWith("1") ? 1 : 2); sockets.set(who, ws); const p = room.participants.find(item => item.id === who); if (p) p.connected = true; room.revision++; ws.send(JSON.stringify({ type: "welcome", participant_id: who })); broadcast(); }
    if (data.type === "play") { assert.equal(data.revision, room.revision); playCommands.push(who); room.state = "playing"; room.revision++; broadcast(); }
   });
   ws.onClose(() => { if (sockets.get(who) === ws) { sockets.delete(who); const p = room.participants.find(item => item.id === who); if (p) p.connected = false; room.revision++; broadcast(); } });
  });
  const page = await context.newPage(); pages.push(page); page.on("pageerror", error => errors.push(error.message)); await page.goto(process.env.APP_URL);
 }
 const [a, b] = pages;
 await b.getByRole("button", { name: "Watch Together" }).waitFor();
 assert.equal(await b.getByRole("button", { name: "Watch Together" }).locator("span").nth(1).isVisible(), true, "mobile label remains visible");
 await a.getByRole("button", { name: "Watch Together" }).click(); await a.getByRole("button", { name: "Create room" }).click();
 await a.getByText("Connected", { exact: true }).first().waitFor();
 await a.getByRole("button", { name: "Copy room code" }).click();
 assert.equal(await a.evaluate(() => window.__copiedText), "482731", "HTTP clipboard fallback copies code");
 await a.getByRole("button", { name: "Copy invite link" }).click();
 assert.equal(await a.evaluate(() => window.__copiedText), `${new URL(process.env.APP_URL).origin}/?join=482731`, "invite uses current origin");
 await b.getByRole("button", { name: "Watch Together" }).click();
 assert.equal(await b.getByRole("textbox", { name: "Room code" }).getAttribute("inputmode"), "numeric");
 await b.getByRole("textbox", { name: "Room code" }).fill("482 731"); await b.getByRole("button", { name: "Join room" }).click();
 await a.waitForFunction(() => document.querySelector(".global-watch-trigger small")?.textContent === "2");
 await a.reload(); await a.getByRole("button", { name: "Watch Together" }).click();
 await a.getByText("Connected", { exact: true }).first().waitFor();
 assert.equal(room.participants.filter(p => p.id === "p1").length, 1, "reload restores same membership");
 await a.getByRole("button", { name: "Leave room" }).click();
 assert.equal(room.status, "open", "creator leaving preserves other participant");
 await b.getByRole("button", { name: "Leave room" }).click();
 assert.equal(room.status, "closed", "last member closes room");
 await b.getByRole("button", { name: "Create room" }).click();
 await b.getByText("Connected", { exact: true }).first().waitFor();
 assert.equal(room.participants[0].profile_id, 2, "viewer profile can create room on mobile");
 await a.getByRole("textbox", { name: "Room code" }).fill("482731"); await a.getByRole("button", { name: "Join room" }).click();
 await a.waitForFunction(() => document.querySelector(".global-watch-trigger small")?.textContent === "2");
 assert.equal(room.participants.length, 2, "desktop joins mobile-created room");
 await b.getByRole("button", { name: "Close menu" }).click();
 await b.getByRole("link", { name: "Search", exact: true }).first().click();
 await b.getByRole("searchbox", { name: "Search Orbis" }).fill("Fixture"); await b.getByRole("link", { name: /Fixture Series/ }).first().click();
 assert.equal(new URL(a.url()).pathname, "/", "ordinary peer browsing is not mirrored");
 await b.getByRole("button", { name: /Play/ }).first().click();
 await Promise.all([a.waitForURL(/\/watch\/1\/tv\/50\/season\/1\/episode\/1/), b.waitForURL(/\/watch\/2\/tv\/50\/season\/1\/episode\/1/)]);
 assert.deepEqual(transitions, [2], "the room creator is not required to approve a peer transition");
 await b.waitForTimeout(350);
 assert.deepEqual(playCommands, ["p2"], "starting peer emits canonical play without waiting for canplay");
 assert.deepEqual(errors, []);
 console.log("PASS targeted Watch Together: mobile label, peer create/join/transition, refresh, clipboard fallback, origin and creator leave");
} finally { await Promise.all(contexts.map(context => context.close())); await browser.close(); }
