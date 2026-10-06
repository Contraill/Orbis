import { Link } from "react-router-dom";

import type { CatalogItem } from "../types";
import { useText } from "../app/i18n";


function releaseYear(date: string | null) {
  return date?.slice(0, 4) || "—";
}


export default function MediaCard({ item }: { item: CatalogItem & { new_season?: number | null } }) {
  const t = useText();
  return (
    <Link
      className="orbis-media-card"
      to={`/${item.media_type}/${item.tmdb_id}`}
    >
      <div className="orbis-poster">
        <span className="poster-fallback" aria-hidden="true">{item.title.slice(0, 1)}</span>
        {item.poster_url ? (
          <img
            src={item.poster_url}
            alt=""
            loading="lazy"
            onError={event => { event.currentTarget.hidden = true; }}
          />
        ) : null}
      </div>
      <strong>{item.title}</strong>
      <small>
        {item.new_season ? `${t("Season")} ${item.new_season}` : `${t(item.media_type === "tv" ? "Series" : "Movies")} · ${releaseYear(item.release_date)}`}
        {item.vote_average !== null
          ? ` · ★ ${item.vote_average.toFixed(1)}`
          : ""}
      </small>
    </Link>
  );
}
