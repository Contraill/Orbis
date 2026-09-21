import React from "react";
import ReactDOM from "react-dom/client";

import AdminProviders from "./AdminProviders";
import "./style.css";


function Home() {
  return (
    <main className="home-page">
      <section className="home-card">
        <p className="eyebrow">ORBIS</p>
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
          href="/admin/providers"
        >
          Provider Manager →
        </a>
      </section>
    </main>
  );
}


function App() {
  if (
    window.location.pathname.startsWith(
      "/admin/providers",
    )
  ) {
    return <AdminProviders />;
  }

  return <Home />;
}


ReactDOM.createRoot(
  document.getElementById("root")!,
).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
