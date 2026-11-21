import {
  NavLink,
  Outlet,
} from "react-router-dom";
import { useProfile } from "../app/ProfileContext";
import OwnerLogin from "../app/OwnerLogin";
import { useText } from "../app/i18n";
import BrandMark from "../app/BrandMark";


const tabs = [
  ["/admin", "Overview", true],
  ["/admin/providers", "Providers", false],
  ["/admin/tests", "Tests", false],
  ["/admin/diagnostics", "Diagnostics", false],
  ["/admin/sessions", "Sessions", false],
  ["/admin/settings", "Settings", false],
] as const;


export default function AdminShell() {
  const { admin, profile } = useProfile();
  const t = useText();
  if (!profile?.is_owner) return <main className="admin-shell"><a href="/">← Orbis</a><p role="alert">{t("Admin access requires the owner profile.")}</p></main>;
  if (!admin) return <main className="product-shell ambient admin-login-page"><div className="admin-login-wrap">
    <BrandMark className="setup-brand" />
    <OwnerLogin />
    <a className="admin-login-back" href="/">{t("Back to Orbis")}</a>
  </div></main>;
  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <a className="back-link" href="/">
            ← Orbis
          </a>

          <p className="eyebrow">
            ORBIS
          </p>

          <h1 className="admin-title">
            Administration
          </h1>
        </div>
      </header>

      <nav className="admin-tabs">
        {tabs.map(([path, label, end]) => (
          <NavLink
            key={path}
            to={path}
            end={end}
            className={({ isActive }) =>
              isActive
                ? "admin-tab active"
                : "admin-tab"
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </main>
  );
}
