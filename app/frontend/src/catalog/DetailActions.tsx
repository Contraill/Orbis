import { useEffect, useState } from "react";
import { getMyList, setListIntent } from "../api";
import type { ContentSelection } from "../types";
import { useProfile } from "../app/ProfileContext";
import { useText } from "../app/i18n";
import { invalidateFeedCache } from "./InfiniteShelfFeed";

export default function DetailActions({ item }: { item: ContentSelection }) {
  const { profile } = useProfile();
  const t = useText();
  const [listed, setListed] = useState(false);
  const [negative, setNegative] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!profile) return;
    let active = true;
    getMyList(profile.id).then(items => { if (active) setListed(items.some(i => i.media_type === item.media_type && i.tmdb_id === item.tmdb_id)); }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : t("Request failed")); });
    return () => { active = false; };
  }, [profile?.id, item.media_type, item.tmdb_id]);
  async function change(isNegative: boolean) {
    if (!profile) return;
    setBusy(true); setError("");
    try { await setListIntent(profile.id, item, isNegative ? !negative : !listed, isNegative); invalidateFeedCache(profile.id); if (isNegative) setNegative(!negative); else setListed(!listed); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("Request failed")); }
    finally { setBusy(false); }
  }
  return <div className="detail-list-actions">
    <button className="orbis-button ghost" disabled={busy} onClick={() => void change(false)}>{listed ? "✓" : "+"} {t(listed ? "Remove from My List" : "Add to My List")}</button>
    <button className="quiet-action" disabled={busy} onClick={() => void change(true)}>{t(negative ? "Clear feedback" : "Not Interested")}</button>
    {error ? <span role="alert" className="form-error">{error}</span> : null}
  </div>;
}
