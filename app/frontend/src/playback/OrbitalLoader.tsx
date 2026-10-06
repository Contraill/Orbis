import { useText } from "../app/i18n";

export default function OrbitalLoader({ embedded = false }: { embedded?: boolean }) {
  const t = useText();
  return <div className={embedded ? "orbital-loading orbital-loading-overlay" : "orbis-player-state orbital-loading"} role="status" aria-live="polite" aria-label={t("Preparing your video…")}>
    <svg className="orbital-acquisition" viewBox="0 0 160 160" aria-hidden="true" focusable="false">
      <circle className="orbital-arc arc-one" cx="80" cy="80" r="51" />
      <circle className="orbital-arc arc-two" cx="80" cy="80" r="38" />
      <circle className="orbital-arc arc-three" cx="80" cy="80" r="62" />
      <circle className="orbital-core" cx="80" cy="80" r="2" />
    </svg>
    <span className={embedded ? "sr-only" : undefined}>{t("Preparing your video…")}</span>
  </div>;
}
