"""Episode markers and bounded client presence."""
from alembic import op
import sqlalchemy as sa
revision = "e64a0c31f952"
down_revision = "d53f9b20e841"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("client_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audience", sa.String(64), nullable=False), sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("client_type", sa.String(32), nullable=False), sa.Column("capabilities", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False), sa.Column("current_playback", sa.JSON()),
        sa.Column("source_session_id", sa.String(128)), sa.Column("position_seconds", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("stopped_at", sa.DateTime(timezone=True)), sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.create_index("ix_client_sessions_profile_id", "client_sessions", ["profile_id"])
    op.create_index("ix_client_sessions_last_seen", "client_sessions", ["last_seen"])
    op.create_table("content_markers", sa.Column("content_key", sa.String(128), primary_key=True),
        sa.Column("markers", sa.JSON(), nullable=False), sa.Column("source", sa.String(100), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("content_markers")
    op.drop_table("client_sessions")
