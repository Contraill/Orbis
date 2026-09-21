import React from "react";
import ReactDOM from "react-dom/client";

import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

import AdminShell from "./admin/AdminShell";
import DiagnosticsPage from "./admin/DiagnosticsPage";
import OverviewPage from "./admin/OverviewPage";
import ProviderEditorPage from "./admin/ProviderEditorPage";
import ProvidersPage from "./admin/ProvidersPage";
import SettingsPage from "./admin/SettingsPage";
import TestsPage from "./admin/TestsPage";

import "./style.css";


function Home() {
  return (
    <main className="home-page">
      <section className="home-card">
        <p className="eyebrow">
          ORBIS
        </p>

        <h1>Media App</h1>

        <p className="home-subtitle">
          Provider-agnostic media platform
        </p>

        <div className="home-status">
          <span className="dot" />
          Frontend online
        </div>

        <a
          className="admin-link"
          href="/admin"
        >
          Administration →
        </a>
      </section>
    </main>
  );
}


function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />

        <Route
          path="/admin"
          element={<AdminShell />}
        >
          <Route index element={<OverviewPage />} />

          <Route
            path="providers"
            element={<ProvidersPage />}
          />

          <Route
            path="providers/:providerId"
            element={<ProviderEditorPage />}
          />

          <Route
            path="tests"
            element={<TestsPage />}
          />

          <Route
            path="diagnostics"
            element={<DiagnosticsPage />}
          />

          <Route
            path="settings"
            element={<SettingsPage />}
          />
        </Route>

        <Route
          path="*"
          element={<Navigate to="/" replace />}
        />
      </Routes>
    </BrowserRouter>
  );
}


ReactDOM.createRoot(
  document.getElementById("root")!,
).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
