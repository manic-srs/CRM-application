import React, { useState } from "react";
import { api } from "./api";
import "./login.css";

export function BrandMark({ size = 40 }) {
  return (
    <span className="brand-mark" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size * 0.6} height={size * 0.6} fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 17l5-5 4 4 7-8" />
        <path d="M15 8h5v5" />
      </svg>
    </span>
  );
}

// Log in. There is no sign up: the Admin creates every account (Users page) and gives you
// your email and password. The backend checks the password (bcrypt) and returns a login token.
export default function Login({ onLogin, sessionExpired = false }) {
  const [values, setValues] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [passwordHelp, setPasswordHelp] = useState(false);
  const set = (name) => (e) => setValues((v) => ({ ...v, [name]: e.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const { user, token } = await api.login(values.email, values.password);
      onLogin(user, token);
    } catch (err) {
      setError(
        /wrong email or password/i.test(err.message)
          ? "Please check your username and password. If you still can't log in, contact your administrator."
          : err.message,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="signin-page">
      <section className="signin-story" aria-label="About SalesTrack">
        <div className="signin-brand"><BrandMark size={44}/><span>SalesTrack</span></div>
        <div className="signin-overview">
          <p className="signin-eyebrow">YOUR SALES WORKSPACE, CONNECTED</p>
          <h1>Smarter sales.{" "}<br/>Stronger relationships.</h1>
          <p className="signin-summary">Bring your team, customers, and opportunities together in one place.</p>
        </div>
        <div className="signin-pipeline" aria-label="Sales pipeline: Leads, Relationships, Opportunities, Closed deals">
          <div className="signin-pipeline-hub"><BrandMark size={44}/></div>
          <div className="signin-pipeline-stages">
            {[['person', 'Leads'], ['people', 'Relationships'], ['chart', 'Opportunities'], ['check', 'Closed deals']].map(([icon, label], index) => (
              <div className={`signin-stage signin-stage-${index}`} key={label}><span><LoginIcon name={icon}/></span><p>{label}</p></div>
            ))}
          </div>
        </div>
        <p className="signin-description">Your CRM portal — manage leads, build your pipeline, and keep every customer conversation moving forward.</p>
        <div className="signin-features">
          {[
            ['person', 'Lead management', 'Capture leads and keep the next step in sight.'],
            ['chart', 'Pipeline visibility', 'Track opportunities from first contact to close.'],
            ['calendar', 'Team productivity', 'Stay on top of tasks, follow-ups, and activities.'],
          ].map(([icon, title, text]) => <article className="signin-feature" key={title}><span className="signin-feature-icon"><LoginIcon name={icon}/></span><h2>{title}</h2><p>{text}</p></article>)}
        </div>
        <div className="signin-story-footer"><span><LoginIcon name="people"/>Connected teams</span><span><LoginIcon name="chart"/>Clearer pipelines</span><span><LoginIcon name="check"/>Better follow-through</span></div>
      </section>
      <section className="signin-panel" aria-labelledby="signin-title">
        <div className="signin-corner-logo">
          <svg className="signin-srs-logo" viewBox="0 0 64 64" role="img" aria-label="SRS logo">
            <circle cx="32" cy="32" r="29" fill="#eb681b"/>
            <circle cx="32" cy="12" r="5" fill="#fff"/>
            <g fill="none" stroke="#fff" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="m18 12 14 20 14-20M32 32v29"/>
              <path d="M15 24c-12 10 12 15 3 29m31-29c12 10-12 15-3 29"/>
            </g>
          </svg>
        </div>
        <div className="signin-content">
          <div className="signin-card">
            <h2 id="signin-title">Sign in</h2>
            <p className="signin-intro">Enter your credentials to access the portal</p>
            <form className="signin-form" onSubmit={submit} aria-busy={busy}>
              {(error || sessionExpired) && <div id="signin-error" className="signin-error" role="alert">{error || "Your session expired. Please sign in again."}</div>}
              <div className="signin-control">
                <label htmlFor="signin-email">Email address</label>
                <div className="signin-field"><LoginIcon name="mail"/><input id="signin-email" name="email" type="email" placeholder="you@company.com" autoComplete="username" value={values.email} onChange={set("email")} required disabled={busy} aria-describedby={error ? "signin-error" : undefined}/></div>
              </div>
              <div className="signin-control">
                <div className="signin-label-row"><label htmlFor="signin-password">Password</label><button type="button" className="signin-forgot" onClick={() => setPasswordHelp(v => !v)} aria-expanded={passwordHelp} aria-controls="signin-password-help">Forgot password?</button></div>
                <div className="signin-field"><LoginIcon name="lock"/><input id="signin-password" name="password" type={showPassword ? "text" : "password"} placeholder="Enter your password" autoComplete="current-password" value={values.password} onChange={set("password")} required disabled={busy} aria-describedby={[error && "signin-error", passwordHelp && "signin-password-help"].filter(Boolean).join(" ") || undefined}/><button className="signin-visibility" type="button" aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword} onClick={() => setShowPassword(v => !v)}><LoginIcon name={showPassword ? "eye" : "eyeOff"}/></button></div>
                {passwordHelp && <p id="signin-password-help" className="signin-password-help" role="status">Contact your SalesTrack administrator to reset your password.</p>}
              </div>
              <button className="signin-submit" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
            </form>
          </div>
          <p className="signin-help">Contact your administrator if you need access or have forgotten your password.</p>
          <p className="signin-account-note"><LoginIcon name="lock"/>Access with your administrator-provided account</p>
        </div>
        <footer className="signin-copyright">© {new Date().getFullYear()} SalesTrack. All rights reserved.</footer>
      </section>
    </main>
  );
}

function LoginIcon({ name }) {
  const paths = {
    person: <><circle cx="12" cy="7" r="4"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></>,
    people: <><circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-17a3 3 0 0 1 0 6m1 4a5 5 0 0 1 3 5v2"/></>,
    chart: <><path d="M4 3v18h17M9 16v-5m5 5V7m5 9V4"/></>,
    check: <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18m-13 5h2m4 0h2"/></>,
    mail: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></>,
    lock: <><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
    eyeOff: <><path d="m3 3 18 18M10 5a13 13 0 0 1 2 0c6 0 10 7 10 7a19 19 0 0 1-3 4M6 6a23 23 0 0 0-4 6s4 7 10 7a13 13 0 0 0 5-1m-7-8a3 3 0 0 0 4 4"/></>,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
