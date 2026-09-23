"""Optional offline ratings import; never runs during application startup.

python -m metadata.ratings /path/to/title.ratings.tsv.gz
Only ratings for IMDb IDs already in Orbis are retained. Re-run after catalog growth.
"""
import argparse
import csv
import gzip
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from db.models.catalog import CatalogEntity, CatalogRating
from db.models.profile import utc_now


def store_rating(db, *, source, external_id, average, votes, scale, provenance):
    if not 0 <= average <= scale or votes < 0 or scale <= 0:
        raise ValueError("Invalid source rating")
    values = dict(source=source, external_id=external_id, average=average, votes=votes, scale=scale, provenance=provenance, fetched_at=utc_now())
    db.execute(insert(CatalogRating).values(**values).on_conflict_do_update(index_elements=["source", "external_id"], set_=values))


def import_imdb(db, path):
    # Memory scales with the local catalog, never with the multi-million-row dataset.
    ids = {f["external_ids"]["imdb"] for f in db.scalars(select(CatalogEntity.features)) if f.get("external_ids", {}).get("imdb")}
    if not ids:
        return 0
    count = 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["tconst", "averageRating", "numVotes"]:
            raise ValueError("Unexpected IMDb ratings dataset columns")
        for row in reader:
            if row["tconst"] in ids:
                store_rating(db, source="imdb", external_id=row["tconst"], average=float(row["averageRating"]), votes=int(row["numVotes"]), scale=10, provenance="https://datasets.imdbws.com/title.ratings.tsv.gz")
                count += 1
    db.commit()
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    args = parser.parse_args()
    from db.session import SessionLocal
    with SessionLocal() as session:
        print(f"Imported {import_imdb(session, args.dataset)} IMDb ratings")
