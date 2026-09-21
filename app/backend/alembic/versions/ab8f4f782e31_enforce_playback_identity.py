"""enforce playback content identity

Revision ID: ab8f4f782e31
Revises: dc92fb544398
Create Date: 2026-09-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ab8f4f782e31"
down_revision: Union[str, Sequence[str], None] = "dc92fb544398"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_playback_movie_identity",
        "playback_states",
        ["profile_id", "tmdb_id"],
        unique=True,
        sqlite_where=sa.text("media_type = 'movie'"),
    )
    op.create_index(
        "uq_playback_episode_identity",
        "playback_states",
        [
            "profile_id",
            "tmdb_id",
            "season_number",
            "episode_number",
        ],
        unique=True,
        sqlite_where=sa.text("media_type = 'tv'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_playback_episode_identity",
        table_name="playback_states",
    )
    op.drop_index(
        "uq_playback_movie_identity",
        table_name="playback_states",
    )
