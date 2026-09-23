"""Durable viewing evidence; resume state is not a recommendation signal.

At most one aggregate per content/UTC day. Seeks and unsampled time are not
counted as viewing. This is household telemetry, not proof of human attention.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.foundation import LibraryIntent, LocalizedMetadata, ViewingDay, ViewingProgress
from db.models.playback import PlaybackState
from db.models.profile import utc_now

MEANINGFUL_SECONDS = 60


def record_progress(db: Session, profile_id, identity, update, now=None):
    now = now or utc_now()
    key = (profile_id, identity.content_key)
    progress = db.get(ViewingProgress, key)
    position = min(update.position_seconds, update.duration_seconds or update.position_seconds)
    if progress is None:
        if position <= 0 and not update.completed:
            return  # Resolution/idle preference saves are not a viewing start.
        progress = ViewingProgress(profile_id=profile_id, content_key=identity.content_key,
            media_type=identity.media_type, tmdb_id=identity.tmdb_id,
            season_number=identity.season_number, episode_number=identity.episode_number,
            started_at=now, last_watched_at=now, sampled_at=now, last_position=position,
            watched_seconds=0, cycle_seconds=0, completions=0, cycle_completed=False,
            rewatches=0, cycle_rewatch_counted=False)
        db.add(progress)
        return
    elapsed = (now - progress.sampled_at).total_seconds()
    if elapsed <= 0:
        return
    delta = position - progress.last_position
    # Support up to 2x playback. A seek is not watching; gaps >2 min are unknown.
    watched = delta if 0 < delta <= elapsed * 2 + 2 and elapsed <= 120 else 0
    if progress.cycle_completed and position < progress.last_position:
        # A player's replay may first save at 15s, not exactly at zero.
        progress.cycle_seconds = 0
        progress.cycle_completed = False
        progress.cycle_rewatch_counted = False
    progress.last_position = position
    progress.sampled_at = now
    if not watched:
        return
    previous_watch = progress.last_watched_at
    progress.watched_seconds += watched
    progress.cycle_seconds += watched
    progress.last_watched_at = now
    day = db.get(ViewingDay, (*key, now.date().isoformat()))
    if day is None:
        day = ViewingDay(profile_id=profile_id, content_key=identity.content_key,
            day=now.date().isoformat(), watched_seconds=0, visits=0, completions=0)
        db.add(day)
    if day.watched_seconds == 0 or now - previous_watch > timedelta(minutes=30):
        day.visits += 1
    day.watched_seconds += watched
    if progress.completions and not progress.cycle_rewatch_counted and progress.cycle_seconds >= MEANINGFUL_SECONDS:
        progress.rewatches += 1
        progress.cycle_rewatch_counted = True
    duration = update.duration_seconds
    reached_end = update.completed or (duration and position >= duration - 10 and position >= duration * .9)
    if reached_end and not progress.cycle_completed and duration and progress.cycle_seconds >= max(MEANINGFUL_SECONDS, duration * .8):
        progress.completions += 1
        day.completions += 1
        progress.cycle_completed = True


def restart(db, profile_id, identity):
    state = db.scalar(select(PlaybackState).where(PlaybackState.profile_id == profile_id, PlaybackState.content_key == identity.content_key))
    if state:
        state.position_seconds = 0
        state.completed = False
    progress = db.get(ViewingProgress, (profile_id, identity.content_key))
    if progress:
        progress.last_position = 0
        progress.sampled_at = utc_now()
        progress.cycle_seconds = 0
        progress.cycle_completed = False
        progress.cycle_rewatch_counted = False


def progress_rows(db, profile_id):
    return list(db.scalars(select(ViewingProgress).where(ViewingProgress.profile_id == profile_id).order_by(ViewingProgress.last_watched_at.desc())))


def metadata(db, media_type, tmdb_id, locale):
    key = f"{media_type}:{tmdb_id}"
    row = db.get(LocalizedMetadata, (key, locale)) or db.get(LocalizedMetadata, (key, "en-US"))
    return row.data if row else None


def next_known_episode(db, state, locale):
    # Only previously fetched, aired episodes; never invent S+1/E+1.
    rows = db.scalars(select(LocalizedMetadata).where(
        LocalizedMetadata.content_key.like(f"tv:{state.tmdb_id}:season:%"),
        LocalizedMetadata.locale.in_([locale, "en-US"])))
    candidates = set()
    today = utc_now().date().isoformat()
    for row in rows:
        season = row.data.get("season_number", 0)
        for episode in row.data.get("episodes", []):
            number = episode.get("episode_number", 0)
            aired = episode.get("air_date")
            if aired and aired <= today and (season, number) > (state.season_number, state.episode_number):
                candidates.add((season, number))
    return min(candidates) if candidates else None


def continue_watching(db, profile, kind="all"):
    states = db.scalars(select(PlaybackState).where(PlaybackState.profile_id == profile.id).order_by(PlaybackState.updated_at.desc(), PlaybackState.id.desc())).all()
    evidence = {p.content_key: p for p in progress_rows(db, profile.id)}
    totals = {}
    for p in evidence.values():
        key = (p.media_type, p.tmdb_id)
        totals[key] = totals.get(key, 0) + p.watched_seconds
    intents = {(i.media_type, i.tmdb_id): i for i in db.scalars(select(LibraryIntent).where(LibraryIntent.profile_id == profile.id))}
    seen, result = set(), []
    for state in states:
        if kind != "all" and state.media_type != kind:
            continue
        key = (state.media_type, state.tmdb_id)
        if key in seen:
            continue
        progress = evidence.get(state.content_key)
        # Resume is a convenience, not an affinity signal. An old resumable state
        # must not vanish when its first new activity sample is still short.
        if (not progress or progress.watched_seconds < MEANINGFUL_SECONDS) and state.position_seconds < MEANINGFUL_SECONDS and not state.completed:
            continue
        seen.add(key)
        intent = intents.get(key)
        if intent and intent.hidden_at and totals.get(key, 0) - intent.hidden_watched_seconds < MEANINGFUL_SECONDS:
            continue
        season, episode = state.season_number, state.episode_number
        action = "resume"
        position = state.position_seconds
        if state.completed:
            if state.media_type == "movie":
                continue
            following = next_known_episode(db, state, profile.locale)
            if not following:
                continue
            season, episode = following
            position, action = 0, "next_episode"
        elif position < 5:
            continue
        result.append({"profile_id": profile.id, "media_type": state.media_type, "tmdb_id": state.tmdb_id,
            "season_number": season, "episode_number": episode, "position_seconds": position,
            "duration_seconds": state.duration_seconds if action == "resume" else None,
            "completed": False, "action": action, "updated_at": state.updated_at,
            "metadata": metadata(db, *key, profile.locale)})
    return result


def recommendation_features(db, profile):
    """Stable boundary for future recommendation consumers; no provider/playback URLs."""
    now = utc_now()
    grouped = {}
    for p in progress_rows(db, profile.id):
        key = (p.media_type, p.tmdb_id)
        item = grouped.setdefault(key, {"media_type": p.media_type, "tmdb_id": p.tmdb_id,
            "watched_seconds": 0, "meaningful_episodes": 0, "completions": 0, "rewatches": 0,
            "first_watched_at": p.started_at, "last_watched_at": p.last_watched_at,
            "active_days": set(), "return_visits": 0, "onboarding": False, "my_list": False, "not_interested": False})
        item["watched_seconds"] += p.watched_seconds
        item["meaningful_episodes"] += int(p.media_type == "tv" and p.watched_seconds >= MEANINGFUL_SECONDS)
        item["completions"] += p.completions
        item["rewatches"] += p.rewatches
        item["first_watched_at"] = min(item["first_watched_at"], p.started_at)
        item["last_watched_at"] = max(item["last_watched_at"], p.last_watched_at)
        for day in db.scalars(select(ViewingDay).where(ViewingDay.profile_id == profile.id, ViewingDay.content_key == p.content_key)):
            if day.watched_seconds >= MEANINGFUL_SECONDS:
                item["active_days"].add(day.day)
                item["return_visits"] += day.visits
    intents = db.scalars(select(LibraryIntent).where(LibraryIntent.profile_id == profile.id)).all()
    seeds = {(s["media_type"], s["tmdb_id"]) for s in profile.onboarding_seeds}
    for key in seeds | {(i.media_type, i.tmdb_id) for i in intents}:
        grouped.setdefault(key, {"media_type": key[0], "tmdb_id": key[1], "watched_seconds": 0,
            "meaningful_episodes": 0, "completions": 0, "rewatches": 0, "first_watched_at": None,
            "last_watched_at": None, "active_days": set(), "return_visits": 0,
            "onboarding": False, "my_list": False, "not_interested": False})
    for key in seeds:
        grouped[key]["onboarding"] = True
    for intent in intents:
        item = grouped[(intent.media_type, intent.tmdb_id)]
        item["my_list"], item["not_interested"] = intent.in_my_list, intent.not_interested
    for item in grouped.values():
        item["active_days"] = sorted(item["active_days"])
        item["sustained_series_progression"] = item["meaningful_episodes"] >= 2 and len(item["active_days"]) >= 2
        item["meaningful_viewing"] = item["watched_seconds"] >= MEANINGFUL_SECONDS
        item["stale_started"] = bool(item["last_watched_at"] and not item["completions"] and now - item["last_watched_at"] >= timedelta(days=30))
    return list(grouped.values())
