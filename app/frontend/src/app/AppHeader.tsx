import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { useDirectionalFocus } from "./useDirectionalFocus";
import { useProfile } from "./ProfileContext";
import { useText } from "./i18n";
import ProfileAvatar from "./ProfileAvatar";
import GlobalRoomControl from "../watch/GlobalRoomControl";
import { useGlobalWatchTogether } from "../watch/GlobalWatchTogether";

const links = [
  ["/", "Home"], ["/movies", "Movies"], ["/series", "Series"],
  ["/library", "My List"], ["/search", "Search"],
] as const;

function NavIcon({ index }: { index: number }) {
  const paths = [
    <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" /><path d="M9 21v-8h6v8" /></>,
    <><rect x="3" y="5" width="18" height="15" rx="2" /><path d="M3 10h18M7 5l3 5m3-5 3 5" /></>,
    <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 4v16m12-12H4m8 4 5 3-5 3z" /></>,
    <><path d="M12 21s-8-4.8-8-11a4.5 4.5 0 0 1 8-2.7A4.5 4.5 0 0 1 20 10c0 6.2-8 11-8 11z" /></>,
    <><circle cx="10.8" cy="10.8" r="6.6" /><path d="m16 16 5 5" /></>,
  ];
  return <svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[index]}</svg>;
}

export default function AppHeader() {
  const { profile, clearProfile } = useProfile();
  const watch = useGlobalWatchTogether();
  const [menu, setMenu] = useState(false);
  const menuRoot = useRef<HTMLDivElement>(null);
  const t = useText();
  useDirectionalFocus();
  useEffect(() => {
    if (!menu) return;
    function outside(event: MouseEvent | TouchEvent) {
      if (!menuRoot.current?.contains(event.target as Node)) setMenu(false);
    }
    function escape(event: KeyboardEvent) { if (event.key === "Escape") { event.stopPropagation(); setMenu(false); } }
    document.addEventListener("mousedown", outside);
    document.addEventListener("touchstart", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("touchstart", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [menu]);
  return <>
    <header className="orbis-header">
      <Link className="orbis-brand" to="/" aria-label={t("Orbis Home")}>
        <img className="brand-wordmark" src="/brand/wordmark.png" alt="Orbis" />
        <img className="brand-icon" src="/brand/standalone-icon.png" alt="Orbis" />
      </Link>
      <nav className="orbis-nav" aria-label={t("Main navigation")}>
        {links.map(([to, label]) => <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => isActive ? "active" : ""}>{t(label)}</NavLink>)}
      </nav>
      <GlobalRoomControl />
      <div className="orbis-account" ref={menuRoot}>
        <button className="account-trigger" type="button" aria-expanded={menu} aria-label={`${t("Switch profile")}: ${profile?.name ?? ""}`} onClick={() => setMenu(!menu)}>
          <ProfileAvatar seed={profile?.avatar_seed || "Orbis"} config={profile?.avatar_config} size={36} /><span className="account-name">{profile?.name}</span><span className="account-chevron" aria-hidden="true">⌄</span>
        </button>
        {menu ? <div className="account-menu">
          <div className="account-menu-identity"><ProfileAvatar seed={profile?.avatar_seed || "Orbis"} config={profile?.avatar_config} size={32} /><strong>{profile?.name}</strong></div>
          <button type="button" onClick={() => { if (watch.room && !window.confirm(t("Switching profiles leaves this Watch Together room. Continue?"))) return; if (watch.room) void watch.leave(); clearProfile(); setMenu(false); }}>{t("Switch profile")}</button>
          <Link to="/profile" onClick={() => setMenu(false)}>{t("Manage profile")}</Link>
          {profile?.is_owner ? <Link to="/admin" onClick={() => setMenu(false)}>{t("Admin")}</Link> : null}
        </div> : null}
      </div>
    </header>
    <nav className="orbis-mobile-nav" aria-label={t("Mobile navigation")}>
      {links.map(([to, label], index) => <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => isActive ? "active" : ""}><NavIcon index={index} /><small>{t(label)}</small></NavLink>)}
    </nav>
  </>;
}
