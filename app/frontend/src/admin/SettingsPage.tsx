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
          can be edited from each live provider.
        </p>

        <p className="muted">
          Global circuit-breaker and playback policy
          controls will move here when they become
          user-configurable.
        </p>
      </article>
    </section>
  );
}
