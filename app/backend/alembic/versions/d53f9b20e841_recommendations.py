"""Derived recommendation feature index."""
from alembic import op
import sqlalchemy as sa

revision = "d53f9b20e841"
down_revision = "c42e8a19d730"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_viewing_progress_profile_media", "viewing_progress", ["profile_id", "media_type", "tmdb_id"])
    op.create_index("ix_catalog_entities_updated_at", "catalog_entities", ["updated_at"])
    op.create_table("catalog_features",
        sa.Column("term", sa.String(160), primary_key=True),
        sa.Column("media_key", sa.String(128), sa.ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True))
    op.create_index("ix_catalog_features_media_key", "catalog_features", ["media_key"])
    from sqlalchemy.orm import Session
    from recommendations.features import reindex_features
    with Session(bind=op.get_bind()) as db:
        for key, in db.execute(sa.text("SELECT key FROM catalog_entities WHERE kind IN ('movie','tv')")).yield_per(100):
            reindex_features(db, key)
        db.commit()


def downgrade():
    op.drop_index("ix_viewing_progress_profile_media", table_name="viewing_progress")
    op.drop_table("catalog_features")
    op.drop_index("ix_catalog_entities_updated_at", table_name="catalog_entities")
