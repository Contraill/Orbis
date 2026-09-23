"""Logical choices; URLs and player-specific variant IDs remain session-only."""
import asyncio
import logging
import re

import httpx

from playback.hls import read_manifest
from playback.schemas import PlaybackChoices, QualityChoice, SourceChoice
from playback.upstream import UpstreamRejected, new_http_client, open_upstream
from providers.source_policy import quality_score, rank_sources

logger = logging.getLogger(__name__)


def manifest_qualities(text: str) -> list[QualityChoice]:
    heights = set()
    pending = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            match = re.search(r'(?:[:,])RESOLUTION=(\d+)x(\d+)(?:,|$)', line)
            pending = int(match[2]) if match else None
        elif line and not line.startswith("#"):
            if pending is not None and 144 <= pending <= 8640:
                heights.add(pending)
            pending = None
    return [QualityChoice(height=h, label=f"{h}p") for h in sorted(heights, reverse=True)]


async def discover_qualities(source) -> list[QualityChoice]:
    if source.protocol != "hls":
        height = quality_score(source.quality)
        return [QualityChoice(height=height, label=f"{height}p")] if height else []
    response = None
    try:
        async with asyncio.timeout(5), new_http_client() as client:
            response, _ = await open_upstream(client, source, source.url)
            if response.status_code != 200:
                return []
            return manifest_qualities(await read_manifest(response))
    except (httpx.HTTPError, OSError, UpstreamRejected, TimeoutError):
        # Discovery is best effort, not an additional prerequisite for playback.
        logger.info("quality_discovery_unavailable provider=%s source=%s", source.provider_id, source.source_id)
        return []
    finally:
        if response is not None:
            await response.aclose()


def selected_height(qualities, preferred):
    heights = [q.height for q in qualities]
    if preferred is None or not heights:
        return None
    lower = [height for height in heights if height <= preferred]
    return max(lower) if lower else min(heights)


def ranked_choices(sources, state, **kwargs):
    ranked = rank_sources(
        sources, preferred_audio_language=state.preferred_audio_language,
        preferred_audio_kind=state.preferred_audio_kind,
        subtitles_enabled=state.subtitles_enabled,
        preferred_subtitle_language=state.preferred_subtitle_language, **kwargs,
    )
    def preference(source):
        height = quality_score(source.quality)
        preferred = state.preferred_quality_height
        quality = (0, 0) if preferred is None or not height else (
            0 if height <= preferred else 1, abs(preferred - height),
        )
        return (not (
            state.preferred_source_id is not None
            and source.provider_id == state.preferred_source_provider_id
            and source.source_id == state.preferred_source_id
        ), quality)
    ranked.sort(key=preference)
    return ranked


async def set_session_choices(session, sources, providers, state):
    qualities = await discover_qualities(session.source)
    if session.source.protocol == "http":
        heights = {quality_score(source.quality) for source in sources
                   if source.source_id == session.source.source_id and source.protocol == "http"}
        qualities = [QualityChoice(height=h, label=f"{h}p") for h in sorted(heights, reverse=True) if h]
    session.context.update(
        sources=sources,
        choices=PlaybackChoices(
            providers=providers,
            sources=[SourceChoice(source_id=key, label=label) for key, label in sorted({
                source.source_id: source.source_label or source.source_id
                for source in sources if source.source_id
            }.items())],
            qualities=qualities,
            selected_quality_height=selected_height(qualities, state.preferred_quality_height),
        ),
    )
