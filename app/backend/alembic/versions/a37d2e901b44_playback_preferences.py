"""Persist logical playback choices, not resolved URLs or variant IDs."""
from alembic import op
import sqlalchemy as sa

revision = "a37d2e901b44"
down_revision = "ab8f4f782e31"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("preferred_provider_id", "preferred_source_provider_id", "preferred_source_id"):
        op.add_column("playback_states", sa.Column(name, sa.String(80), nullable=True))
    op.add_column("playback_states", sa.Column("preferred_quality_height", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("playback_states") as batch:
        for name in ("preferred_quality_height", "preferred_source_id", "preferred_source_provider_id", "preferred_provider_id"):
            batch.drop_column(name)
