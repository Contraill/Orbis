import {
  NavLink,
  Outlet,
} from "react-router-dom";


const tabs = [
  ["/admin", "Overview", true],
  ["/admin/providers", "Providers", false],
  ["/admin/tests", "Tests", false],
  ["/admin/diagnostics", "Diagnostics", false],
  ["/admin/settings", "Settings", false],
] as const;


export default function AdminShell() {
  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <a className="back-link" href="/">
            ← Media App
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
