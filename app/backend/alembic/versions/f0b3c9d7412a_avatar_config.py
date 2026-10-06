"""Persist optional Blobatar customization separately from avatar identity."""
from alembic import op
import sqlalchemy as sa

revision = "f0b3c9d7412a"
down_revision = "e64a0c31f952"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("profiles", sa.Column("avatar_config", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("profiles", "avatar_config")
