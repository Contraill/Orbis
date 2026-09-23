"""Bounded FTS5 candidate retrieval, followed by deterministic fuzzy scoring."""
import re
import unicodedata
from difflib import SequenceMatcher
from sqlalchemy import event, text, select
from db.base import Base


def normalize(value):
    value = unicodedata.normalize("NFKD", value.casefold().replace("ı", "i"))
    return " ".join(re.findall(r"[^\W_]+", "".join(c for c in value if not unicodedata.combining(c)), re.UNICODE))


def grams(value):
    return sorted({word[i:i + 3] for word in normalize(value).split() for i in range(len(word) - 2)})


def create_index(connection):
    connection.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS catalog_fts USING fts5(key UNINDEXED, terms, grams, tokenize='unicode61 remove_diacritics 2', prefix='2 3 4')")


@event.listens_for(Base.metadata, "after_create")
def after_create(metadata, connection, **kw):
    create_index(connection)


@event.listens_for(Base.metadata, "before_drop")
def before_drop(metadata, connection, **kw):
    connection.exec_driver_sql("DROP TABLE IF EXISTS catalog_fts")


def reindex(db, key):
    from db.models.catalog import CatalogEntity, CatalogLink
    from db.models.foundation import LocalizedMetadata
    entity = db.get(CatalogEntity, key)
    if not entity:
        return
    names = {entity.name, *entity.features.get("aliases", [])}
    if entity.kind in ("movie", "tv"):
        for row in db.scalars(select(LocalizedMetadata).where(LocalizedMetadata.content_key == key)):
            names.update([row.data.get("title", ""), row.data.get("original_title", "")])
        names.update(db.scalars(select(CatalogEntity.name).join(CatalogLink, CatalogLink.entity_key == CatalogEntity.key).where(CatalogLink.media_key == key)))
    terms = "\n".join(sorted({normalize(n) for n in names if n}))
    db.execute(text("DELETE FROM catalog_fts WHERE key=:key"), {"key": key})
    db.execute(text("INSERT INTO catalog_fts(key,terms,grams) VALUES (:key,:terms,:grams)"), {"key": key, "terms": terms, "grams": " ".join(grams(terms))})


def candidates(db, query, kind="all", limit=300):
    normalized = normalize(query)
    tokens = normalized.split()[:12]
    if not tokens:
        return []
    prefix = "terms : (" + " OR ".join('"' + t + '"*' for t in tokens) + ")"
    trigram = grams(normalized)[:60]
    matches = [prefix]
    if trigram:
        matches.append('grams : (' + ' OR '.join('"' + t + '"' for t in trigram) + ')')
    rows = {}
    for match in matches:
        for row in db.execute(text("SELECT f.key,f.terms FROM catalog_fts f JOIN catalog_entities e ON e.key=f.key WHERE catalog_fts MATCH :match AND (:kind='all' OR e.kind=:kind) ORDER BY bm25(catalog_fts), f.key LIMIT :limit"), {"match": match, "kind": kind, "limit": limit}):
            rows[row.key] = row.terms
    ranked = []
    for key, terms in rows.items():
        score = 0
        for name in terms.splitlines():
            if normalized == name:
                value = 100
            elif name.startswith(normalized):
                value = 95
            elif normalized in name:
                value = 90
            else:
                value = 100 * SequenceMatcher(None, normalized, name, autojunk=False).ratio()
                words = name.split()
                if len(tokens) == 1:
                    value = max([value] + [100 * SequenceMatcher(None, normalized, w, autojunk=False).ratio() for w in words])
            score = max(score, value)
        if score >= 68:
            ranked.append((key, round(score, 3)))
    return sorted(ranked, key=lambda v: (-v[1], v[0]))
