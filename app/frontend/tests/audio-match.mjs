import assert from "node:assert/strict";
import { chooseManifestAudio, audioMatches, activeAudioLabel } from "../src/player/audioMatch.ts";

const variant = (id, language, label, primary = false) => ({
  id, language, audioLanguage: language, originalLanguage: "en", label,
  primary, bandwidth: 2_000_000, audioRoles: [], roles: [], kind: "main",
});
const english = variant(22, "en", "English original", true);
const turkish = variant(21, "tr", "Türkçe dub");
const tracks = [english, turkish];

const providerDub = { track_id: "22", language: "tr", label: "Türkçe dub", kind: "dub" };
assert.equal(chooseManifestAudio(tracks, providerDub)?.id, 21, "provider ID must never alias a Shaka ID");
assert.equal(audioMatches(turkish, providerDub), true);
assert.equal(audioMatches(english, providerDub), false);
assert.equal(audioMatches(english, { track_id: "22", language: null, label: null, kind: "dub" }), false, "original rendition is not a successful dub switch");

const providerOriginal = { track_id: "original-provider-id", language: null, label: "Original", kind: "original" };
assert.equal(chooseManifestAudio(tracks, providerOriginal)?.id, 22);
assert.equal(audioMatches(english, providerOriginal, "en"), true);
assert.equal(audioMatches(turkish, providerOriginal, "en"), false);
assert.equal(activeAudioLabel(turkish), "Turkish");
assert.equal(chooseManifestAudio([turkish], providerOriginal, "en"), null, "unavailable original audio must not be shown as selected");
const untaggedOriginal = { ...english, language: "und", audioLanguage: "und", originalLanguage: null, primary: false, label: "Original Audio" };
assert.equal(chooseManifestAudio([{ ...turkish, language: "und", audioLanguage: "und", originalLanguage: null, label: "Turkish" }, untaggedOriginal], providerOriginal, "en")?.label, "Original Audio");
assert.equal(activeAudioLabel(untaggedOriginal, "en", "en-US"), "English");
console.log("PASS semantic Shaka audio selection: provider IDs ignored, dub/original intent and active-track verification");
