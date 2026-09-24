export default function SettingsPage() {
  return (
    <section className="admin-page">
      <div className="page-heading">
        <div>
          <p className="section-kicker">
            CONFIGURATION
          </p>

          <h2>Settings</h2>
        </div>
      </div>

      <article className="panel">
        <h3>Provider subsystem</h3>

        <p className="muted">
          Provider-specific settings are stored
          outside Git under /config/providers and
          can be edited from each provider editor. Fields are declared by the
          active provider; secrets are stored server-side and are never returned.
        </p>

        <p className="muted">
          Providers without a settings schema display “No configurable settings”.
          Enabled state, priority, source and quality remain separate controls.
        </p>
      </article>
    </section>
  );
}
