import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { catalogCredits, unifiedSearch, type SearchPage, type SearchResult } from "../api";

type RequestSpec = { query: string; kind: string; online: boolean } | { kind: "person" | "company"; id: number };

export default function SearchVerification() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [online, setOnline] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [spec, setSpec] = useState<RequestSpec | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);

  async function load(request: RequestSpec, next?: string) {
    const id = ++generation.current;
    setBusy(true); setError(""); setSpec(request);
    if (!next) { setResults([]); setCursor(null); }
    try {
      const page: SearchPage = "id" in request
        ? await catalogCredits(request.kind, request.id, next)
        : await unifiedSearch(request.query, request.kind, request.online, next);
      if (id !== generation.current) return;
      setResults(old => next ? [...old, ...page.results] : page.results);
      setCursor(page.next_cursor); setError(page.warning || "");
    } catch (reason) {
      if (id === generation.current) setError(String(reason));
    } finally {
      if (id === generation.current) setBusy(false);
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim()) void load({ query: query.trim(), kind, online });
  }
  return <section className="catalog-section" aria-label="Catalog search verification">
    <h2>Catalog search</h2>
    <p>Search titles in either language, people or companies. Display follows your profile language.</p>
    <form className="catalog-search" onSubmit={submit}>
      <label>Query <input value={query} onChange={event => setQuery(event.target.value)} placeholder="interstelar / christoper nolan" maxLength={200} /></label>
      <label>Results <select value={kind} onChange={event => setKind(event.target.value)}>
        <option value="all">All</option><option value="movie">Movies</option><option value="tv">Series</option><option value="person">People</option><option value="company">Companies</option>
      </select></label>
      <label><input type="checkbox" checked={online} onChange={event => setOnline(event.target.checked)} /> Include TMDB beyond cached matches</label>
      <button className="button primary" disabled={busy || !query.trim()}>Search</button>
    </form>
    {error ? <p role="alert">{error}</p> : null}
    {busy ? <p role="status">Loading…</p> : null}
    {!busy && spec && !results.length && !error ? <p>No results on this page.</p> : null}
    {(["movie", "tv", "person", "company"] as const).map(group => {
      const items = results.filter(item => item.kind === group);
      if (!items.length) return null;
      return <div key={group}><h3>{{ movie: "Movies", tv: "Series", person: "People", company: "Companies" }[group]}</h3><ul>
        {items.map(item => <li key={item.key}>
          {item.kind === "movie" || item.kind === "tv"
            ? <Link to={`/${item.kind}/${item.tmdb_id}`}>{item.title}</Link>
            : <button type="button" disabled={busy} onClick={() => void load({ kind: item.kind as "person" | "company", id: item.tmdb_id })}>{item.title} — discover credits</button>}
          {item.roles.length ? ` · ${item.roles.join(", ")}` : ""}{item.display_locale ? ` · ${item.display_locale}` : ""}
        </li>)}
      </ul></div>;
    })}
    {cursor && spec ? <button className="button secondary" disabled={busy} onClick={() => void load(spec, cursor)}>Load more</button> : null}
  </section>;
}
