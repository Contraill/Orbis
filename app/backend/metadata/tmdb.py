import httpx

from core.config import get_settings
from metadata.schemas import (
    CatalogDetails,
    CatalogItem,
    CatalogPage,
    EpisodeSummary,
    SeasonDetails,
)


TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"


class TMDBError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def image_url(path: str | None, size: str) -> str | None:
    if not path:
        return None

    return f"{TMDB_IMAGE_BASE_URL}/{size}{path}"


def catalog_item(data: dict) -> CatalogItem | None:
    media_type = data.get("media_type")

    if media_type == "movie":
        title = data.get("title") or data.get("original_title")
        original_title = data.get("original_title")
        release_date = data.get("release_date")
    elif media_type == "tv":
        title = data.get("name") or data.get("original_name")
        original_title = data.get("original_name")
        release_date = data.get("first_air_date")
    else:
        return None

    if not title:
        return None

    return CatalogItem(
        tmdb_id=data["id"],
        media_type=media_type,
        title=title,
        original_title=original_title,
        overview=data.get("overview") or "",
        poster_url=image_url(data.get("poster_path"), "w500"),
        backdrop_url=image_url(data.get("backdrop_path"), "w1280"),
        release_date=release_date or None,
        vote_average=data.get("vote_average"),
    )


class TMDBClient:
    def __init__(self, locale: str | None = None):
        self.locale = locale

    async def _get(
        self,
        path: str,
        params: dict | None = None,
    ) -> dict:
        settings = get_settings()

        if not settings.tmdb_api_key:
            raise TMDBError(503, "TMDB is not configured")

        request_params = {
            "api_key": settings.tmdb_api_key,
            "language": self.locale or settings.tmdb_language,
        }

        if params:
            request_params.update(params)

        try:
            async with httpx.AsyncClient(
                base_url=TMDB_BASE_URL,
                timeout=10.0,
            ) as client:
                response = await client.get(
                    path,
                    params=request_params,
                )
        except httpx.RequestError as exc:
            raise TMDBError(502, "TMDB request failed") from exc

        if response.status_code == 404:
            raise TMDBError(404, "TMDB item not found")

        if response.status_code in {401, 403}:
            raise TMDBError(503, "TMDB authentication failed")

        if response.status_code == 429:
            raise TMDBError(503, "TMDB rate limit reached")

        if response.is_error:
            raise TMDBError(502, "TMDB returned an upstream error")

        try:
            return response.json()
        except ValueError as exc:
            raise TMDBError(
                502,
                "TMDB returned an invalid response",
            ) from exc

    async def search(
        self,
        query: str,
        page: int,
    ) -> CatalogPage:
        data = await self._get(
            "/search/multi",
            {
                "query": query,
                "page": page,
                "include_adult": False,
            },
        )

        results = []

        for item in data.get("results", []):
            normalized = catalog_item(item)
            if normalized is not None:
                results.append(normalized)

        return CatalogPage(
            page=data.get("page", page),
            total_pages=data.get("total_pages", 0),
            results=results,
        )

    async def trending(
        self,
        window: str,
    ) -> CatalogPage:
        data = await self._get(f"/trending/all/{window}")

        results = []

        for item in data.get("results", []):
            normalized = catalog_item(item)
            if normalized is not None:
                results.append(normalized)

        return CatalogPage(
            page=data.get("page", 1),
            total_pages=data.get("total_pages", 1),
            results=results,
        )

    async def movie_details(
        self,
        tmdb_id: int,
    ) -> CatalogDetails:
        data = await self._get(f"/movie/{tmdb_id}", {"append_to_response": "credits,keywords,external_ids,alternative_titles,videos,similar,recommendations"})

        return CatalogDetails(
            **rich_fields(data),
            tmdb_id=data["id"],
            media_type="movie",
            title=data.get("title") or data.get("original_title") or "Untitled",
            original_title=data.get("original_title"),
            overview=data.get("overview") or "",
            poster_url=image_url(data.get("poster_path"), "w500"),
            backdrop_url=image_url(data.get("backdrop_path"), "w1280"),
            release_date=data.get("release_date") or None,
            vote_average=data.get("vote_average"),
            genres=[
                genre["name"]
                for genre in data.get("genres", [])
                if genre.get("name")
            ],
            runtime_minutes=data.get("runtime"),
            status=data.get("status"),
        )

    async def tv_details(
        self,
        tmdb_id: int,
    ) -> CatalogDetails:
        data = await self._get(f"/tv/{tmdb_id}", {"append_to_response": "credits,keywords,external_ids,alternative_titles,videos,similar,recommendations"})

        runtimes = data.get("episode_run_time") or []

        return CatalogDetails(
            **rich_fields(data),
            tmdb_id=data["id"],
            media_type="tv",
            title=data.get("name") or data.get("original_name") or "Untitled",
            original_title=data.get("original_name"),
            overview=data.get("overview") or "",
            poster_url=image_url(data.get("poster_path"), "w500"),
            backdrop_url=image_url(data.get("backdrop_path"), "w1280"),
            release_date=data.get("first_air_date") or None,
            vote_average=data.get("vote_average"),
            genres=[
                genre["name"]
                for genre in data.get("genres", [])
                if genre.get("name")
            ],
            runtime_minutes=runtimes[0] if runtimes else None,
            status=data.get("status"),
            number_of_seasons=data.get("number_of_seasons"),
            number_of_episodes=data.get("number_of_episodes"),
        )

    async def season_details(
        self,
        series_tmdb_id: int,
        season_number: int,
    ) -> SeasonDetails:
        data = await self._get(
            f"/tv/{series_tmdb_id}/season/{season_number}"
        )

        episodes = [
            EpisodeSummary(
                tmdb_id=episode.get("id"),
                episode_number=episode["episode_number"],
                name=episode.get("name") or "",
                overview=episode.get("overview") or "",
                air_date=episode.get("air_date") or None,
                still_url=image_url(
                    episode.get("still_path"),
                    "w500",
                ),
                runtime_minutes=episode.get("runtime"),
                vote_average=episode.get("vote_average"),
            )
            for episode in data.get("episodes", [])
        ]

        return SeasonDetails(
            series_tmdb_id=series_tmdb_id,
            season_tmdb_id=data["id"],
            season_number=data["season_number"],
            name=data.get("name") or f"Season {season_number}",
            overview=data.get("overview") or "",
            air_date=data.get("air_date") or None,
            poster_url=image_url(data.get("poster_path"), "w500"),
            episodes=episodes,
        )


def rich_fields(data):
    def refs(values):
        return [{"tmdb_id": v["id"], "name": v["name"]} for v in values if v.get("id") and v.get("name")]
    credits = []
    for c in data.get("credits", {}).get("cast", []):
        credits.append({"tmdb_id": c["id"], "name": c["name"], "role": "Actor", "character": c.get("character") or "", "order": c.get("order")})
    for c in data.get("credits", {}).get("crew", []):
        credits.append({"tmdb_id": c["id"], "name": c["name"], "role": c.get("job") or "Crew", "department": c.get("department")})
    for c in data.get("created_by", []):
        credits.append({"tmdb_id": c["id"], "name": c["name"], "role": "Creator"})
    keywords = data.get("keywords", {})
    alternatives = data.get("alternative_titles", {})
    kind = "tv" if "first_air_date" in data or "number_of_seasons" in data else "movie"
    return dict(
        genre_refs=refs(data.get("genres", [])),
        keywords=refs(keywords.get("keywords", keywords.get("results", []))),
        aliases=sorted({a["title"] for a in alternatives.get("titles", alternatives.get("results", [])) if a.get("title")}),
        external_ids={k.removesuffix("_id"): str(v) for k, v in data.get("external_ids", {}).items() if v is not None and k != "id"},
        original_language=data.get("original_language"),
        countries=sorted(set(data.get("origin_country", []) + [c["iso_3166_1"] for c in data.get("production_countries", [])])),
        production_companies=refs(data.get("production_companies", [])), credits=credits,
        videos=[{"site": v["site"], "key": v["key"], "name": v.get("name", ""), "language": v.get("iso_639_1"), "country": v.get("iso_3166_1"), "type": v.get("type", "Unknown"), "official": v.get("official", False), "published_at": v.get("published_at")} for v in data.get("videos", {}).get("results", [])],
        seasons=[{"tmdb_id": v["id"], "season_number": v["season_number"], "name": v.get("name", ""), "overview": v.get("overview") or "", "air_date": v.get("air_date"), "episode_count": v.get("episode_count", 0), "poster_url": image_url(v.get("poster_path"), "w500")} for v in data.get("seasons", [])],
        related=[{"media_type": kind, "tmdb_id": v["id"], "relation": relation} for relation in ("similar", "recommendations") for v in data.get(relation, {}).get("results", [])],
    )
