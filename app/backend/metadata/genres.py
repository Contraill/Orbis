"""TMDB genre IDs and localized names used for catalog navigation.

Only IDs present in the local feature index become shelves. TV's combined
Action & Adventure and Sci-Fi & Fantasy IDs share the corresponding movie
category when browsing across both media types.
"""

NAMES = {
    28: ("Action", "Aksiyon"), 12: ("Adventure", "Macera"),
    16: ("Animation", "Animasyon"), 35: ("Comedy", "Komedi"),
    80: ("Crime", "Suç"), 99: ("Documentary", "Belgesel"),
    18: ("Drama", "Drama"), 10751: ("Family", "Aile"),
    14: ("Fantasy", "Fantastik"), 36: ("History", "Tarih"),
    27: ("Horror", "Korku"), 10402: ("Music", "Müzik"),
    9648: ("Mystery", "Gizem"), 10749: ("Romance", "Romantik"),
    878: ("Science Fiction", "Bilim Kurgu"), 10770: ("TV Movie", "TV Filmi"),
    53: ("Thriller", "Gerilim"), 10752: ("War", "Savaş"),
    37: ("Western", "Western"), 10759: ("Action & Adventure", "Aksiyon ve Macera"),
    10762: ("Kids", "Çocuk"), 10763: ("News", "Haber"),
    10764: ("Reality", "Reality"), 10765: ("Sci-Fi & Fantasy", "Bilim Kurgu ve Fantastik"),
    10766: ("Soap", "Pembe Dizi"), 10767: ("Talk", "Söyleşi"),
    10768: ("War & Politics", "Savaş ve Politika"),
}

PAIRS = {28: 10759, 878: 10765}


def genre_ids(genre_id: int, scope: str) -> tuple[int, ...]:
    if scope != "all":
        if scope == "movie":
            return (next((movie for movie, tv in PAIRS.items() if tv == genre_id), genre_id),)
        return (PAIRS.get(genre_id, genre_id),)
    partner = PAIRS.get(genre_id)
    if partner is None:
        partner = next((movie for movie, tv in PAIRS.items() if tv == genre_id), None)
    return (genre_id, partner) if partner is not None else (genre_id,)


def label(genre_id: int, scope: str, locale: str) -> str | None:
    names = NAMES.get(genre_id)
    if not names:
        return None
    name = names[1 if locale == "tr-TR" else 0]
    if genre_id == 10770:
        return "TV Filmleri" if locale == "tr-TR" else "TV Movies"
    if genre_id == 10749 and locale == "tr-TR":
        return "Romantik Filmler" if scope == "movie" else "Romantik Filmler ve Diziler"
    if scope == "movie":
        return f"{name} Filmleri" if locale == "tr-TR" else f"{name} Movies"
    if scope == "tv":
        return f"{name} Dizileri" if locale == "tr-TR" else f"{name} Series"
    return f"{name} Filmleri ve Dizileri" if locale == "tr-TR" else f"{name} Movies & Series"


def search(query: str, scope: str, locale: str) -> list[dict]:
    """Small, deterministic bilingual lookup of canonical genre identities."""
    from difflib import SequenceMatcher
    from metadata.index import normalize

    needle = normalize(query)
    if len(needle) < 2:
        return []
    merged = {}
    for genre_id, (english, turkish) in NAMES.items():
        canonical = next((movie for movie, tv in PAIRS.items() if tv == genre_id), genre_id)
        if scope == "movie" and genre_id in PAIRS.values():
            continue
        if scope == "tv" and genre_id in PAIRS:
            continue
        names = [english, turkish]
        names += [label(genre_id, kind, language) or "" for kind in ("all", "movie", "tv") for language in ("en-US", "tr-TR")]
        normalized = [normalize(name) for name in names]
        score = max(100 if needle == name else 92 if name.startswith(needle) else 86 if needle in name
            else round(100 * SequenceMatcher(None, needle, name, autojunk=False).ratio()) for name in normalized)
        if score < 68:
            continue
        target = canonical if genre_id in PAIRS.values() else genre_id
        if target not in merged or score > merged[target][0]:
            merged[target] = (score, {"genre_id": target, "title": label(target, scope, locale), "scope": scope})
    return [item for _, item in sorted(merged.values(), key=lambda row: (-row[0], row[1]["genre_id"]))[:8]]
