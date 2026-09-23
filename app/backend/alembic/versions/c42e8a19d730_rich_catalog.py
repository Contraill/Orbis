"""Canonical catalog cache and bounded FTS search."""
from alembic import op
import sqlalchemy as sa

revision = "c42e8a19d730"
down_revision = "b91f02a7c640"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("catalog_entities", sa.Column("key", sa.String(128), primary_key=True), sa.Column("kind", sa.String(16), nullable=False), sa.Column("tmdb_id", sa.Integer(), nullable=False), sa.Column("name", sa.String(512), nullable=False), sa.Column("features", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_catalog_entities_kind", "catalog_entities", ["kind"])
    op.create_table("catalog_links", sa.Column("media_key", sa.String(128), sa.ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True), sa.Column("entity_key", sa.String(128), sa.ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True), sa.Column("role", sa.String(128), primary_key=True), sa.Column("character", sa.String(512), primary_key=True))
    op.create_index("ix_catalog_links_entity_role", "catalog_links", ["entity_key", "role", "media_key"])
    op.create_table("catalog_seasons", sa.Column("series_key", sa.String(128), sa.ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True), sa.Column("season_number", sa.Integer(), primary_key=True), sa.Column("tmdb_id", sa.Integer(), nullable=False), sa.Column("air_date", sa.String(10)), sa.Column("episode_count", sa.Integer()))
    op.create_table("catalog_episodes", sa.Column("series_key", sa.String(128), sa.ForeignKey("catalog_entities.key", ondelete="CASCADE"), primary_key=True), sa.Column("season_number", sa.Integer(), primary_key=True), sa.Column("episode_number", sa.Integer(), primary_key=True), sa.Column("tmdb_id", sa.Integer()), sa.Column("air_date", sa.String(10)), sa.Column("runtime_minutes", sa.Integer()))
    op.create_table("catalog_ratings", sa.Column("source", sa.String(64), primary_key=True), sa.Column("external_id", sa.String(128), primary_key=True), sa.Column("average", sa.Float(), nullable=False), sa.Column("votes", sa.Integer(), nullable=False), sa.Column("scale", sa.Float(), nullable=False), sa.Column("provenance", sa.String(512), nullable=False), sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("catalog_search_cache", sa.Column("key", sa.String(64), primary_key=True), sa.Column("data", sa.JSON(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_catalog_search_cache_expires_at", "catalog_search_cache", ["expires_at"])
    op.execute("CREATE VIRTUAL TABLE catalog_fts USING fts5(key UNINDEXED, terms, grams, tokenize='unicode61 remove_diacritics 2', prefix='2 3 4')")
    # Stream existing localizations through the same canonical normalization path.
    from sqlalchemy.orm import Session
    from metadata.catalog import ingest
    import json
    connection = op.get_bind()
    with Session(bind=connection) as db:
        for data, in connection.execute(sa.text("SELECT data FROM localized_metadata")).yield_per(100):
            ingest(db, json.loads(data) if isinstance(data, str) else data, update_features=False)
        db.commit()


def downgrade():
    op.execute("DROP TABLE catalog_fts")
    for name in ("catalog_search_cache", "catalog_ratings", "catalog_episodes", "catalog_seasons", "catalog_links", "catalog_entities"):
        op.drop_table(name)
