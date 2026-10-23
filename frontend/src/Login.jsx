import React, { useState } from "react";
import { api } from "./api";

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
export default function Login({ onLogin }) {
  const [values, setValues] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
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
    <div className="login-page">
      <div className="login-wrap">
        <div className="login-brand">
          <BrandMark size={56} />
          <span>SalesTrack</span>
        </div>
        <form className="login-box" onSubmit={submit}>
          <h1 className="login-title">Log in</h1>
          {error && (
            <div className="login-error" role="alert">
              {error}
            </div>
          )}
          <label>
            Username
            <input type="email" autoComplete="username" value={values.email} onChange={set("email")} required autoFocus />
          </label>
          <label>
            Password
            <input type="password" autoComplete="current-password" value={values.password} onChange={set("password")} required />
          </label>
          <button className="login-button" disabled={busy}>
            {busy ? "Logging in…" : "Log In"}
          </button>
          <p className="login-switch">Don't have an account? Contact your administrator to add you.</p>
        </form>
      </div>
    </div>
  );
}
