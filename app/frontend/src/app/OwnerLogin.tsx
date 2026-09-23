import { useState, type FormEvent } from "react";
import { loginOwner } from "../api";
import { useProfile } from "./ProfileContext";
import { useText } from "./i18n";

export default function OwnerLogin() {
  const { setup, authenticate } = useProfile();
  const t = useText();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { const result = await loginOwner(password); setPassword(""); await authenticate(result.token); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Request failed"); }
    finally { setBusy(false); }
  }
  return <section className="panel"><h2>{t("Owner login")}</h2>
    {!setup?.owner_password_configured ? <><p>{t("Owner password is not configured. Run the local owner setup command.")}</p><code>docker compose exec backend python -m core.owner</code></> :
      <form className="foundation-form" onSubmit={submit}>
        <label>{t("Password")}<input type="password" required maxLength={128} autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
        <button className="button secondary" disabled={busy}>{t("Sign in")}</button>
        {error ? <p role="alert">{t(error)}</p> : null}
      </form>}
  </section>;
}
