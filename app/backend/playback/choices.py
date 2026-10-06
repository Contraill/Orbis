"""Logical choices; URLs and player-specific variant IDs remain session-only."""
import asyncio
import logging
import re

import httpx

from playback.hls import read_manifest
from playback.schemas import PlaybackChoices, QualityChoice, SourceChoice
from playback.quality import quality_class
from playback.upstream import UpstreamRejected, new_http_client, open_upstream
from providers.source_policy import quality_score, rank_sources

from playback.capabilities import current_capabilities, source_compatible, filter_hls, request_client

logger = logging.getLogger(__name__)


def manifest_qualities(text: str) -> list[QualityChoice]:
    classes = {}
    pending = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            match = re.search(r'(?:[:,])RESOLUTION=(\d+)x(\d+)(?:,|$)', line)
            pending = (int(match[1]), int(match[2])) if match else None
        elif line and not line.startswith("#"):
            if pending is not None and 144 <= pending[1] <= 8640:
                tier = quality_class(*pending)
                if tier:
                    classes.setdefault(tier, set()).add(pending)
            pending = None
    return [QualityChoice(height=tier, label=f"{tier}p", encoded_variants=[
        {"width": width, "height": height}
        for width, height in sorted(classes[tier], key=lambda size: (size[0] * size[1], size[1]), reverse=True)
    ]) for tier in sorted(classes, reverse=True)]


def _compatible_quality(choice, caps):
    if not caps or not caps.max_height:
        return choice
    if choice.encoded_variants:
        variants = [item for item in choice.encoded_variants if item.height <= caps.max_height]
        return choice.model_copy(update={"encoded_variants": variants}) if variants else None
    return choice if choice.height <= caps.max_height else None


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
            text = await read_manifest(response)
            ctx = request_client.get()
            if ctx is not None:
                ctx["advertised_heights"] = {q.height for q in manifest_qualities(text)}
            return manifest_qualities(filter_hls(text, current_capabilities()))
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
    caps = kwargs.pop("capabilities", current_capabilities())
    ranked = rank_sources(
        [s for s in sources if source_compatible(s, caps)], preferred_audio_language=state.preferred_audio_language,
        preferred_audio_kind=state.preferred_audio_kind,
        subtitles_enabled=state.subtitles_enabled,
        preferred_subtitle_language=state.preferred_subtitle_language,
        preferred_quality_height=state.preferred_quality_height,
        preferred_source_provider_id=state.preferred_source_provider_id,
        preferred_source_id=state.preferred_source_id, **kwargs,
    )
    return ranked


async def set_session_choices(session, sources, providers, state):
    caps = current_capabilities(session.context.get("capabilities"))
    advertised = {quality_score(s.quality) for s in sources if s.source_id == session.source.source_id and s.protocol == "http"}
    sources = [s for s in sources if source_compatible(s, caps)]
    session.context["capabilities"] = caps
    ctx = request_client.get()
    if ctx:
        session.context["client_session_id"] = ctx["id"]
        ctx.pop("advertised_heights", None)
    qualities = await discover_qualities(session.source)
    if ctx is not None:
        advertised |= ctx.pop("advertised_heights", set())
    if session.source.protocol == "http":
        heights = {quality_score(source.quality) for source in sources
                   if source.source_id == session.source.source_id and source.protocol == "http"}
        qualities = [QualityChoice(height=h, label=f"{h}p") for h in sorted(heights, reverse=True) if h]
    if caps and caps.max_height:
        qualities = [compatible for q in qualities if (compatible := _compatible_quality(q, caps))]
    session.context.update(
        incompatible_heights=advertised - {q.height for q in qualities},
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


def quality_result(choices, preferred, caps, incompatible_heights=()):
    compatible = [value for q in choices.qualities if (value := _compatible_quality(q, caps))]
    selected = selected_height(compatible, preferred)
    max_height = caps.max_height if caps else None
    if preferred is None:
        outcome = "auto"
    elif preferred in incompatible_heights or caps and caps.max_height and not any(q.height == preferred for q in compatible) and preferred > caps.max_height:
        outcome = "incompatible_fallback"
    elif not compatible:
        outcome = "unverified"
    else:
        outcome = "exact" if selected == preferred else "unavailable_fallback"
    return choices.model_copy(update={"qualities": compatible, "selected_quality_height": selected,
        "max_compatible_height": max_height, "quality_outcome": outcome})
