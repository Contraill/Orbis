import { useState, type FormEvent } from "react";
import { ApiError, loginOwner } from "../api";
import { useProfile } from "./ProfileContext";
import { useText } from "./i18n";

export default function OwnerLogin() {
  const { setup, authenticate } = useProfile();
  const t = useText();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { const result = await loginOwner(password); setPassword(""); await authenticate(result.token); }
    catch (reason) { setError(reason instanceof ApiError && reason.status === 401 ? "Invalid owner credentials" : reason instanceof ApiError && reason.status === 429 ? "Try again later" : "Request failed"); }
    finally { setBusy(false); }
  }
  return <section className="admin-login-card"><span className="orbis-kicker">ORBIS / {t("Admin")}</span><h1>{t("Admin access")}</h1><p>{t("Sign in to manage Orbis")}</p>
    {!setup?.owner_password_configured ? <><p>{t("Owner password is not configured. Run the local owner setup command.")}</p><code>docker compose exec backend python -m core.owner</code></> :
      <form className="admin-login-form" onSubmit={submit}>
        <label htmlFor="owner-password">{t("Password")}</label>
        <div className="admin-password-field"><input id="owner-password" autoFocus type={showPassword ? "text" : "password"} required maxLength={128} autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} aria-invalid={Boolean(error)} aria-describedby={error ? "owner-login-error" : undefined} />
          <button type="button" onClick={() => setShowPassword(value => !value)} aria-label={t(showPassword ? "Hide password" : "Show password")}>{t(showPassword ? "Hide password" : "Show password")}</button></div>
        {error ? <p id="owner-login-error" className="form-error" role="alert">{t(error)}</p> : null}
        <button className="orbis-button accent admin-signin" disabled={busy}>{t(busy ? "Signing in…" : "Sign in")}</button>
      </form>}
  </section>;
}
