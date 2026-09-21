import { Link } from "react-router-dom";

import type { CatalogItem } from "../types";


function releaseYear(date: string | null) {
  return date?.slice(0, 4) || "—";
}


export default function MediaCard({ item }: { item: CatalogItem }) {
  return (
    <Link
      className="media-card"
      to={`/${item.media_type}/${item.tmdb_id}`}
    >
      <div className="media-poster">
        {item.poster_url ? (
          <img
            src={item.poster_url}
            alt=""
            loading="lazy"
          />
        ) : (
          <span>{item.title.slice(0, 1)}</span>
        )}
        <span className="media-kind">
          {item.media_type === "tv" ? "Series" : "Movie"}
        </span>
      </div>
      <strong>{item.title}</strong>
      <small>
        {releaseYear(item.release_date)}
        {item.vote_average !== null
          ? ` · ★ ${item.vote_average.toFixed(1)}`
          : ""}
      </small>
    </Link>
  );
}
