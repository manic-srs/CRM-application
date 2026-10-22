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

// Must match the roles allowed by the backend (users.role in database/schema.sql)
const ROLES = ["Salesperson", "Manager", "Admin"];

// Login and Sign Up. The backend checks the password (bcrypt); there are no tokens yet (POC).
export default function Login({ onLogin }) {
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [values, setValues] = useState({ full_name: "", email: "", password: "", confirm: "", role: "Salesperson" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (name) => (e) => setValues((v) => ({ ...v, [name]: e.target.value }));
  const signup = mode === "signup";

  const switchMode = (next) => {
    setMode(next);
    setError("");
    setValues((v) => ({ ...v, password: "", confirm: "" }));
  };

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (signup && values.password !== values.confirm) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      const { user } = signup ? await api.signup(values) : await api.login(values.email, values.password);
      onLogin(user);
    } catch (err) {
      setError(
        !signup && /wrong email or password/i.test(err.message)
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
          <h1 className="login-title">{signup ? "Create your account" : "Log in"}</h1>
          {error && (
            <div className="login-error" role="alert">
              {error}
            </div>
          )}
          {signup && (
            <label>
              Full Name
              <input value={values.full_name} onChange={set("full_name")} autoComplete="name" required minLength={2} maxLength={100} autoFocus />
            </label>
          )}
          <label>
            {signup ? "Work Email" : "Username"}
            <input
              type="email"
              autoComplete={signup ? "email" : "username"}
              value={values.email}
              onChange={set("email")}
              required
              autoFocus={!signup}
            />
          </label>
          {signup && (
            <label>
              Role
              <select value={values.role} onChange={set("role")} required>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            Password
            <input
              type="password"
              autoComplete={signup ? "new-password" : "current-password"}
              value={values.password}
              onChange={set("password")}
              required
              minLength={signup ? 8 : undefined}
            />
          </label>
          {signup && (
            <>
              <label>
                Confirm Password
                <input type="password" autoComplete="new-password" value={values.confirm} onChange={set("confirm")} required />
              </label>
              <p className="login-hint">At least 8 characters, with letters and numbers.</p>
            </>
          )}
          <button className="login-button" disabled={busy}>
            {busy ? (signup ? "Creating account…" : "Logging in…") : signup ? "Sign Up" : "Log In"}
          </button>
          <p className="login-switch">
            {signup ? "Already have an account? " : "New to SalesTrack? "}
            <button type="button" className="link" onClick={() => switchMode(signup ? "login" : "signup")}>
              {signup ? "Log In" : "Sign Up"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
