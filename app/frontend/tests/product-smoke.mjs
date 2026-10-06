// Deterministic product browser fixture. No live backend, provider, or user data.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH ?? "playwright-core");
if (process.env.ORBIS_PRODUCT_FIXTURE !== "1" || !["http://127.0.0.1", "http://media-app-frontend"].includes(process.env.APP_URL)) throw new Error("Explicit isolated product fixture required");

const profile = { id: 1, name: "Mira", avatar: null, avatar_seed: "stable-mira", avatar_config: null, locale: "tr-TR", is_owner: true,
  preferred_audio_language: null, preferred_subtitle_language: null, subtitles_enabled: false, autoplay_next_episode: true, trailer_muted: true, onboarding_seeds: [] };
const viewer = { ...profile, id: 2, name: "Deniz", avatar_seed: "stable-deniz", is_owner: false };
let profiles = [profile, viewer];
const item = (id, media_type) => ({ key: `${media_type}:${id}`, kind: media_type, media_type, tmdb_id: id,
  title: media_type === "movie" && id === 1 ? "Yıldızlararası" : media_type === "tv" && id === 2 ? "Örnek Dizi" : `Yapım ${id}`,
  original_title: null, overview: "Örnek yapım", poster_url: null, backdrop_url: null, release_date: "2020-01-01", vote_average: 8.2 });
const shelf = (id, media_type) => ({ id, kind: "discover", title: id, personalized: false, items: [item(media_type === "movie" ? 1 : 2, media_type)] });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? "/usr/bin/chromium", args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await context.addInitScript(() => localStorage.setItem("media-app.selected-profile.v1", "1"));
const page = await context.newPage();
page.setDefaultTimeout(15000);
const errors = [], feedRequests = { home: [], movies: [], series: [] };
page.on("pageerror", error => errors.push(error.message));
let myList = [{ media_type: "movie", tmdb_id: 1, metadata: item(1, "movie") }];
const json = (route, data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
await page.route("**/api/**", route => {
  const url = new URL(route.request().url()), path = url.pathname;
  if (path === "/api/setup") return json(route, { locale: "tr-TR", setup_required: false, owner_id: 1, owner_password_configured: true });
  if (path === "/api/profiles") return json(route, profiles);
  if (path === "/api/profiles/2/self-delete" && route.request().method() === "POST") {
    assert.equal(route.request().headers()["x-profile-id"], "2");
    assert.deepEqual(route.request().postDataJSON(), { confirm_name: "Deniz" });
    profiles = [profile];
    return route.fulfill({ status: 204, body: "" });
  }
  if (path.startsWith("/api/feeds/profiles/1/")) {
    const surface = path.split("/").at(-1), cursor = url.searchParams.get("cursor"), media = surface === "series" ? "tv" : "movie";
    feedRequests[surface].push(cursor);
    const index = cursor === "two" ? 1 : cursor === "three" ? 2 : 0;
    const shelves = index === 0 ? [{ ...shelf("hero", media), kind: "hero" }, { ...shelf("first", media), kind: "genre", title: surface === "movies" ? "Aksiyon Filmleri" : surface === "series" ? "Aksiyon Dizileri" : "Aksiyon Filmleri ve Dizileri", genre_id: 28, genre_scope: surface === "movies" ? "movie" : surface === "series" ? "tv" : "all" }, shelf("second", media)]
      : index === 1 ? [shelf("third", media), shelf("fourth", media), shelf("fifth", media)]
        : [shelf("sixth", media), shelf("seventh", media), shelf("eighth", media)];
    return json(route, { snapshot_id: "fixture", surface, personalized: false, shelves, next_cursor: index === 0 ? "two" : index === 1 ? "three" : null, warnings: [] });
  }
  if (path.includes("/continue")) return json(route, []);
  if (path.endsWith("/my-list") && route.request().method() === "GET") return json(route, myList);
  if (path.endsWith("/my-list") && route.request().method() === "PUT") { myList = []; return json(route, {}); }
  if (path.endsWith("/states")) return json(route, []);
  if (path === "/api/catalog/unified-search") {
    const query = url.searchParams.get("query")?.toLowerCase() ?? "";
    return json(route, { results: query.includes("interst") ? [{ ...item(1, "movie"), kind: "movie", roles: [] }]
      : query.includes("nolan") ? [{ key: "person:10", kind: "person", tmdb_id: 10, title: "Christopher Nolan", roles: ["Director"] }] : [], next_cursor: null });
  }
  if (path === "/api/catalog/genres") {
    const kind = url.searchParams.get("kind") ?? "all";
    return json(route, { results: url.searchParams.get("query")?.toLowerCase().includes("aksiyon")
      ? [{ genre_id: 28, title: kind === "movie" ? "Aksiyon Filmleri" : kind === "tv" ? "Aksiyon Dizileri" : "Aksiyon Filmleri ve Dizileri", scope: kind }]
      : [] });
  }
  if (path === "/api/catalog/person/10/credits") return json(route, { results: [{ ...item(1, "movie"), kind: "movie", roles: [] }], next_cursor: null });
  if (path === "/api/catalog/genres/28/items") {
    const scope = url.searchParams.get("kind") ?? "all";
    return json(route, { genre_id: 28, scope, title: scope === "movie" ? "Aksiyon Filmleri" : scope === "tv" ? "Aksiyon Dizileri" : "Aksiyon Filmleri ve Dizileri",
      results: scope === "all" ? [item(1, "movie"), item(2, "tv")] : [item(scope === "movie" ? 1 : 2, scope === "movie" ? "movie" : "tv")], next_cursor: null });
  }
  if (path.endsWith("/ratings")) return json(route, { ratings: [] });
  if (path === "/api/catalog/movie/1" || path === "/api/catalog/tv/2") {
    const media_type = path.includes("/movie/") ? "movie" : "tv", id = media_type === "movie" ? 1 : 2;
    return json(route, { ...item(id, media_type), original_title: media_type === "movie" ? "Interstellar" : "Example Series", genres: ["Drama"],
      runtime_minutes: 120, credits: [], production_companies: [], videos: [], related: [], seasons: media_type === "tv" ? [{ season_number: 1, episode_count: 1, name: "Sezon 1" }] : [], number_of_seasons: media_type === "tv" ? 1 : null });
  }
  if (path === "/api/catalog/tv/2/season/1") return json(route, { series_tmdb_id: 2, season_number: 1, episodes: [{ episode_number: 1, name: "Pilot", overview: "İlk bölüm", air_date: "2020-01-01", still_url: null }] });
  return json(route, { error: { code: "fixture_missing", message: path } }, 404);
});

async function scrollFeed(surface, path) {
  await page.goto(process.env.APP_URL + path);
  await page.locator('[data-shelf-id="first"]').waitFor();
  assert.equal(feedRequests[surface][0], null);
  for (let attempt = 0; attempt < 30 && (feedRequests[surface].length < 3 || await page.locator("[data-shelf-id]").count() < 8); attempt++) {
    await page.locator(".shelf-sentinel").scrollIntoViewIfNeeded();
    await page.waitForTimeout(260);
  }
  assert.deepEqual(feedRequests[surface], [null, "two", "three"]);
  assert.equal(await page.locator("[data-shelf-id]").count(), 8);
  assert.equal(await page.getByText("Şimdilik tüm rafları gördün").count(), 0);
  await page.getByRole("link", { name: /Aksiyon/ }).first().click();
  await page.getByRole("heading", { name: /Aksiyon/ }).waitFor();
  await page.locator('.genre-grid a').first().waitFor();
  assert.equal(new URL(page.url()).searchParams.get("scope"), surface === "movies" ? "movie" : surface === "series" ? "tv" : "all");
  if (surface === "home") assert.equal(await page.locator('.genre-grid a[href^="/movie/"]').count(), 1);
  if (surface === "home") assert.equal(await page.locator('.genre-grid a[href^="/tv/"]').count(), 1);
  if (surface === "movies") assert.equal(await page.locator('[data-shelf-id] a[href^="/tv/"]').count(), 0);
  if (surface === "series") assert.equal(await page.locator('[data-shelf-id] a[href^="/movie/"]').count(), 0);
}

try {
  await scrollFeed("home", "/");
  await scrollFeed("movies", "/movies");
  await scrollFeed("series", "/series");
  await page.goto(process.env.APP_URL + "/profile");
  await page.locator(".avatar-option-group").first().waitFor();
  assert.equal(await page.getByRole("button", { name: "Profili sil" }).count(), 0);
  assert.equal(await page.locator(".avatar-option-group").nth(0).locator(".avatar-option").count(), 10);
  assert.equal(await page.locator(".avatar-option-group").nth(1).locator(".avatar-option").count(), 14);
  assert.equal(await page.getByLabel("Avatar anahtarı").count(), 0);
  assert.equal(await page.locator('input[type="color"]').count(), 1);
  assert.equal(await page.locator('.avatar-color-swatch').count(), 0);
  assert.equal(await page.locator('.avatar-option-track').first().evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
  assert.equal(await page.locator('input[type="color"]').inputValue(), await page.locator('.avatar-customizer-preview svg').evaluate(node => getComputedStyle(node).getPropertyValue('--mo-head').trim()));
  const previousHead = await page.locator('.avatar-customizer-preview svg').evaluate(node => getComputedStyle(node).getPropertyValue('--mo-head').trim());
  await page.locator('input[type="color"]').fill('#44ddaa');
  assert.notEqual(await page.locator('.avatar-customizer-preview svg').evaluate(node => getComputedStyle(node).getPropertyValue('--mo-head').trim()), previousHead);
  await page.getByRole("button", { name: /Profil değiştir/ }).click();
  assert.equal(await page.getByRole("link", { name: "Profil Ekle" }).count(), 0);
  assert.equal(await page.getByRole("link", { name: "Profili düzenle" }).count(), 1);
  await page.getByRole("button", { name: "Profil değiştir", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Profili düzenle" }).count(), 0);
  assert.equal(await page.getByRole("link", { name: "Profil Ekle" }).count(), 1);
  await page.getByRole("button", { name: "Deniz" }).click();
  await page.getByRole("button", { name: "Profili sil", exact: true }).click();
  await page.getByRole("button", { name: "Profili kalıcı olarak sil" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Profili kalıcı olarak sil" }).isDisabled(), true);
  await page.getByLabel(/Silmeyi onaylamak için profil adını yaz/).fill("Deniz");
  await page.getByRole("button", { name: "Profili kalıcı olarak sil" }).click();
  await page.getByRole("heading", { name: "Kim izliyor?" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Deniz" }).count(), 0);
  await page.getByRole("button", { name: "Mira" }).click();
  await page.goto(process.env.APP_URL + "/search");
  await page.getByRole("searchbox").fill("aksiyon");
  await page.getByRole("link", { name: /Aksiyon Filmleri ve Dizileri/ }).waitFor();
  await page.getByRole("link", { name: /Aksiyon Filmleri ve Dizileri/ }).click();
  await page.getByRole("heading", { name: /Aksiyon/ }).waitFor();
  await page.goto(process.env.APP_URL + "/search");
  await page.getByRole("searchbox").fill("interst");
  await page.getByRole("link", { name: /Yıldızlararası/ }).waitFor();
  await page.getByRole("searchbox").fill("christoper nolan");
  await page.getByRole("button", { name: /Christopher Nolan/ }).click();
  await page.getByRole("heading", { name: "Christopher Nolan" }).waitFor();
  await page.getByRole("link", { name: /Yıldızlararası/ }).waitFor();
  await page.goto(process.env.APP_URL + "/movie/1");
  await page.getByRole("heading", { name: "Yıldızlararası" }).waitFor();
  await page.evaluate(() => localStorage.setItem("orbis.pending-taste.1", "1"));
  await page.goto(process.env.APP_URL + "/profiles/1/taste");
  await page.getByRole("searchbox", { name: "Ara" }).fill("interst");
  await page.getByRole("button", { name: /Yıldızlararası/ }).waitFor();
  await page.evaluate(() => localStorage.removeItem("orbis.pending-taste.1"));
  await page.goto(process.env.APP_URL + "/library");
  await page.getByRole("link", { name: "Yıldızlararası" }).waitFor();
  await page.getByRole("button", { name: /Listemden kaldır/ }).click();
  await page.getByText("Kaydettiğin yapımlar burada görünecek.").waitFor();
  for (const [width, height] of [[390, 844], [1920, 1080]]) {
    await page.setViewportSize({ width, height });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
  }
  assert.deepEqual(errors, []);
  console.log("PASS product fixture: feed continuation, category scope, profile self-delete, search, detail, list and responsive widths");
} finally { await browser.close(); }
