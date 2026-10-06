import React, { useLayoutEffect } from "react";
import ReactDOM from "react-dom/client";

import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigationType,
} from "react-router-dom";

import { ProfileProvider } from "./app/ProfileContext";
import DetailPage from "./catalog/DetailPage";
import HomePage from "./catalog/HomePage";
import { lazy, Suspense } from "react";
const PlaybackPage = lazy(() => import("./playback/PlaybackPage"));
const SearchPage = lazy(() => import("./catalog/SearchPage"));
const GenrePage = lazy(() => import("./catalog/GenrePage"));
const AdminShell = lazy(() => import("./admin/AdminShell"));
const DiagnosticsPage = lazy(() => import("./admin/DiagnosticsPage"));
const OverviewPage = lazy(() => import("./admin/OverviewPage"));
const ProviderEditorPage = lazy(() => import("./admin/ProviderEditorPage"));
const ProvidersPage = lazy(() => import("./admin/ProvidersPage"));
const SessionsPage = lazy(() => import("./admin/SessionsPage"));
const SettingsPage = lazy(() => import("./admin/SettingsPage"));
const TestsPage = lazy(() => import("./admin/TestsPage"));

import "./style.css";
import "./product.css";
import "./silk-glass.css";
import SetupGate from "./app/SetupGate";
import ProfileSettings from "./app/ProfileSettings";
import AddProfilePage from "./app/AddProfilePage";
import TasteSelection from "./app/TasteSelection";
import MyListPage from "./catalog/MyListPage";
import { invalidateFeedCache } from "./catalog/InfiniteShelfFeed";
import { useText } from "./app/i18n";
import OrbisSilkBackground from "./app/OrbisSilkBackground";
import { GlobalWatchTogetherProvider } from "./watch/GlobalWatchTogether";
import TvConnectionGuard from "./app/TvConnectionGuard";

function RouteLoading() { const t = useText(); return <div className="product-loading" role="status">{t("Loading…")}</div>; }

const scrollPositions = new Map<string, number>();
let previousPath = "";
function RouteScroll() {
  const location = useLocation();
  const type = useNavigationType();
  useLayoutEffect(() => {
    if (previousPath.startsWith("/watch/") && !location.pathname.startsWith("/watch/")) invalidateFeedCache();
    previousPath = location.pathname;
    window.scrollTo(0, type === "POP" ? scrollPositions.get(location.key) ?? 0 : 0);
    return () => { scrollPositions.set(location.key, window.scrollY); if (scrollPositions.size > 50) scrollPositions.delete(scrollPositions.keys().next().value!); };
  }, [location.key, type]);
  return null;
}


function App() {
  return (
    <ProfileProvider>
      <BrowserRouter>
        <GlobalWatchTogetherProvider>
        <OrbisSilkBackground />
        <TvConnectionGuard />
        <RouteScroll />
        <SetupGate>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/movies" element={<HomePage surface="movies" />} />
          <Route path="/series" element={<HomePage surface="series" />} />
          <Route path="/profile" element={<ProfileSettings />} />
          <Route path="/profiles/new" element={<AddProfilePage />} />
          <Route path="/profiles/:id/taste" element={<TasteSelection />} />
          <Route path="/library" element={<MyListPage />} />
          <Route path="/search" element={<Suspense fallback={<RouteLoading />}><SearchPage /></Suspense>} />
          <Route path="/genre/:genreId" element={<Suspense fallback={<RouteLoading />}><GenrePage /></Suspense>} />

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
            element={<Suspense fallback={<RouteLoading />}><PlaybackPage /></Suspense>}
          />

          <Route
            path="/watch/:profileId/:mediaType/:tmdbId"
            element={<Suspense fallback={<RouteLoading />}><PlaybackPage /></Suspense>}
          />

          <Route
            path="/admin"
            element={<Suspense fallback={<RouteLoading />}><AdminShell /></Suspense>}
          >
            <Route index element={<OverviewPage />} />
            <Route path="sessions" element={<SessionsPage />} />

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
        </SetupGate>
        </GlobalWatchTogetherProvider>
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
