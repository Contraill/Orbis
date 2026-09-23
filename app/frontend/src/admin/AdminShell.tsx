import {
  NavLink,
  Outlet,
} from "react-router-dom";
import { useProfile } from "../app/ProfileContext";
import OwnerLogin from "../app/OwnerLogin";


const tabs = [
  ["/admin", "Overview", true],
  ["/admin/providers", "Providers", false],
  ["/admin/tests", "Tests", false],
  ["/admin/diagnostics", "Diagnostics", false],
  ["/admin/sessions", "Sessions", false],
  ["/admin/settings", "Settings", false],
] as const;


export default function AdminShell() {
  const { admin } = useProfile();
  if (!admin) return <main className="admin-shell"><a href="/">← Orbis</a><OwnerLogin /></main>;
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
