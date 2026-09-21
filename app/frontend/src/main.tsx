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
import { ProfileProvider } from "./app/ProfileContext";
import DetailPage from "./catalog/DetailPage";
import HomePage from "./catalog/HomePage";
import PlaybackPage from "./playback/PlaybackPage";

import "./style.css";


function App() {
  return (
    <ProfileProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />

          <Route
            path="/movie/:tmdbId"
            element={<DetailPage mediaType="movie" />}
          />

          <Route
            path="/tv/:tmdbId"
            element={<DetailPage mediaType="tv" />}
          />

          <Route
            path={
              "/watch/:profileId/:mediaType/:tmdbId" +
              "/season/:seasonNumber/episode/:episodeNumber"
            }
            element={<PlaybackPage />}
          />

          <Route
            path="/watch/:profileId/:mediaType/:tmdbId"
            element={<PlaybackPage />}
          />

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
    </ProfileProvider>
  );
}


ReactDOM.createRoot(
  document.getElementById("root")!,
).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
