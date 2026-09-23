"""Profile foundation, installation authority, localized metadata and activity.

Revision ID: b91f02a7c640
Revises: a37d2e901b44
"""
from alembic import op
import sqlalchemy as sa

revision = "b91f02a7c640"
down_revision = "a37d2e901b44"
branch_labels = None
depends_on = None


def upgrade():
    for column in [
        sa.Column("avatar_seed", sa.String(255), nullable=False, server_default="orbis"),
        sa.Column("locale", sa.String(5), nullable=False, server_default="en-US"),
        sa.Column("is_owner", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("preferred_audio_language", sa.String(32)),
        sa.Column("preferred_subtitle_language", sa.String(32)),
        sa.Column("subtitles_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("autoplay_next_episode", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("trailer_muted", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("onboarding_seeds", sa.JSON(), nullable=False, server_default="[]"),
    ]:
        op.add_column("profiles", column)
    op.execute("UPDATE profiles SET avatar_seed = name")
    op.execute("UPDATE profiles SET is_owner = 1 WHERE id = (SELECT MIN(id) FROM profiles)")
    op.create_index("uq_profiles_owner", "profiles", ["is_owner"], unique=True, sqlite_where=sa.text("is_owner = 1"))
    op.create_table("installation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("profiles.id", ondelete="RESTRICT")),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1", name="installation_singleton"))
    op.execute("INSERT INTO installation (id, locale, owner_id, failed_logins) SELECT 1, 'en-US', MIN(id), 0 FROM profiles")
    op.create_table("admin_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("localized_metadata",
        sa.Column("content_key", sa.String(128), primary_key=True),
        sa.Column("locale", sa.String(5), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("viewing_progress",
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("content_key", sa.String(128), primary_key=True),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("season_number", sa.Integer()), sa.Column("episode_number", sa.Integer()),
        *[sa.Column(n, sa.DateTime(timezone=True), nullable=False) for n in ("started_at", "last_watched_at", "sampled_at")],
        *[sa.Column(n, sa.Float(), nullable=False) for n in ("last_position", "watched_seconds", "cycle_seconds")],
        sa.Column("completions", sa.Integer(), nullable=False),
        sa.Column("cycle_completed", sa.Boolean(), nullable=False),
        sa.Column("rewatches", sa.Integer(), nullable=False),
        sa.Column("cycle_rewatch_counted", sa.Boolean(), nullable=False))
    op.create_table("viewing_days",
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("content_key", sa.String(128), primary_key=True),
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("watched_seconds", sa.Float(), nullable=False),
        sa.Column("visits", sa.Integer(), nullable=False),
        sa.Column("completions", sa.Integer(), nullable=False))
    op.create_table("library_intents",
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("media_type", sa.String(16), primary_key=True),
        sa.Column("tmdb_id", sa.Integer(), primary_key=True),
        sa.Column("in_my_list", sa.Boolean(), nullable=False),
        sa.Column("listed_at", sa.DateTime(timezone=True)),
        sa.Column("not_interested", sa.Boolean(), nullable=False),
        sa.Column("feedback_at", sa.DateTime(timezone=True)),
        sa.Column("hidden_at", sa.DateTime(timezone=True)),
        sa.Column("hidden_watched_seconds", sa.Float(), nullable=False))


def downgrade():
    for table in ("library_intents", "viewing_days", "viewing_progress", "localized_metadata", "admin_sessions", "installation"):
        op.drop_table(table)
    with op.batch_alter_table("profiles") as batch:
        batch.drop_index("uq_profiles_owner")
        for name in ("avatar_seed", "locale", "is_owner", "preferred_audio_language", "preferred_subtitle_language", "subtitles_enabled", "autoplay_next_episode", "trailer_muted", "onboarding_seeds"):
            batch.drop_column(name)
