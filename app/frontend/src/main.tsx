import React from "react";
import ReactDOM from "react-dom/client";
import "./style.css";

function App() {
  return (
    <main className="page">
      <section>
        <p className="eyebrow">ORBIS</p>
        <h1>Media App</h1>
        <p className="subtitle">Yeni medya platformu çalışıyor.</p>
        <div className="status">
          <span className="dot"></span>
          Frontend online
        </div>
      </section>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
