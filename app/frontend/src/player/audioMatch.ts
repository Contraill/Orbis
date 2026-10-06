import type shaka from "shaka-player";
import type { AudioTrack } from "../types";

type Variant = shaka.extern.Track;

const language = (value: string | null | undefined) => value?.trim().replace(/_/g, "-").toLowerCase() ?? "";
const base = (value: string) => value.split("-")[0];
const words = (value: string | null | undefined) => value?.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim() ?? "";
const isOriginal = (value: string) => /\boriginal\b|\borijinal\b/.test(value);
const isDub = (value: string) => /\bdub\b|dubbed|dubbing|dublaj/.test(value);

function trackLanguage(track: Variant) {
  const value = language(track.audioLanguage || track.language);
  return value === "und" ? "" : value;
}

function requestedLanguage(selected: AudioTrack, contentOriginalLanguage?: string | null) {
  return language(selected.language || (selected.kind === "original" ? contentOriginalLanguage : null));
}

function description(track: Variant) {
  return words([track.label, track.kind, ...(track.audioRoles ?? []), ...track.roles].join(" "));
}

function intentScore(track: Variant, selected: AudioTrack, contentOriginalLanguage?: string | null): number {
  const actual = trackLanguage(track);
  const requested = requestedLanguage(selected, contentOriginalLanguage);
  const label = words(track.label);
  const selectedLabel = words(selected.label);
  const semantic = description(track);
  let score = 0;
  if (requested && actual) score += actual === requested ? 150 : base(actual) === base(requested) ? 110 : -150;
  if (selectedLabel && label) score += selectedLabel === label ? 100 : label.includes(selectedLabel) ? 35 : 0;
  if (selected.kind === "original") {
    if (isOriginal(semantic)) score += 85;
    if (isDub(semantic)) score -= 100;
    if (track.primary && !isDub(semantic)) score += 8;
  } else if (selected.kind === "dub") {
    if (isDub(semantic)) score += 65;
    if (isOriginal(semantic)) score -= 80;
  } else if (selected.kind === "commentary") {
    score += /commentary|comment/.test(semantic) ? 80 : -100;
  } else if (/commentary|comment/.test(semantic)) score -= 80;
  return score;
}

export function audioMatches(track: Variant | undefined, selected: AudioTrack, contentOriginalLanguage?: string | null): boolean {
  if (!track) return false;
  const requested = requestedLanguage(selected, contentOriginalLanguage);
  const actual = trackLanguage(track);
  const semantic = description(track);
  if (requested && actual && base(requested) !== base(actual)) return false;
  if (selected.kind === "original") {
    if (isDub(semantic)) return false;
    if (requested && actual) return true;
    return isOriginal(semantic) || Boolean(track.originalLanguage && actual === language(track.originalLanguage));
  }
  if (selected.kind === "dub" && isOriginal(semantic)) return false;
  if (selected.kind === "commentary") return /commentary|comment/.test(semantic);
  if (requested && actual) return true;
  if (selected.label && words(selected.label) === words(track.label)) return true;
  return selected.kind === "dub" && isDub(semantic);
}

export function chooseManifestAudio(tracks: Variant[], selected: AudioTrack, contentOriginalLanguage?: string | null): Variant | null {
  // Provider track_id and Shaka rendition id are unrelated namespaces.
  return [...tracks].filter(track => audioMatches(track, selected, contentOriginalLanguage))
    .sort((a, b) => intentScore(b, selected, contentOriginalLanguage) - intentScore(a, selected, contentOriginalLanguage)
      || Number(b.primary) - Number(a.primary) || b.bandwidth - a.bandwidth || a.id - b.id)[0] ?? null;
}

export function activeAudioLabel(track: Variant | undefined, contentOriginalLanguage?: string | null, locale = "en-US"): string | null {
  if (!track) return null;
  const actual = trackLanguage(track);
  const resolved = actual || (isOriginal(words(track.label)) ? language(contentOriginalLanguage) : "");
  if (resolved) {
    try { return new Intl.DisplayNames([locale], { type: "language" }).of(resolved) ?? track.label ?? resolved; }
    catch { return track.label ?? resolved; }
  }
  return track.label || track.audioLanguage || track.language || null;
}
