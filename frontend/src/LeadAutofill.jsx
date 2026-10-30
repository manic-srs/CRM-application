// LinkedIn Profile URL at the top of the lead form. On New Lead, a complete profile address (pasted, or typed and
// then paused) is looked up in Apollo through the backend, and the details found fill the fields that are empty.
// - Each profile is looked up once per form (pasting it again, or going back to it, reuses the answer).
// - A newer address always wins: an older answer that arrives late is never applied.
// - Values the user typed or changed are never touched. Unchanged autofill from a previous address is replaced,
//   or removed when the address is cleared or the new one has no value for that field.
// - Nothing is saved or sent here; Save runs the usual checks (required fields, duplicate email).
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { AUTOFILL_FIELDS, autofillPlan, linkedInProfileUrl } from "./domain";
import { Icon } from "./ui";

const TYPING_PAUSE = 800; // ms after the last key before a typed address is looked up
const names = (list) => list.map((name) => AUTOFILL_FIELDS[name]).join(", ");

export default function LinkedInField({ autofill, defaultValue, form, onCompany }) {
  const [status, setStatus] = useState({ kind: "idle" });
  const enabled = useRef(null); // null until the server says whether Apollo is set up
  const answers = useRef(new Map()); // profile address -> Apollo's answer, for this form only
  const pending = useRef(new Map()); // profile address -> the lookup in progress
  const current = useRef(""); // the profile address now in the field ("" = none or not valid)
  const filled = useRef({}); // values Apollo filled that the user hasn't changed
  const welcome = useRef({ unticked: false, touched: false });
  const timer = useRef(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    if (!autofill) return undefined;
    api
      .leadEnrichmentStatus()
      .then((res) => {
        enabled.current = !!res.enabled;
        if (alive.current && !res.enabled) setStatus((s) => (s.kind === "idle" ? { kind: "off" } : s));
      })
      .catch(() => {});
    // A field the user changes is theirs from then on; ticking the welcome email again is respected.
    const element = form();
    const onEdit = (event) => {
      const { name } = event.target;
      if (name === "welcome_email") welcome.current.touched = true;
      if (name in filled.current && event.target.value !== filled.current[name]) {
        delete filled.current[name];
        event.target.classList.remove("autofilled");
      }
    };
    element?.addEventListener("input", onEdit);
    element?.addEventListener("change", onEdit);
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
      element?.removeEventListener("input", onEdit);
      element?.removeEventListener("change", onEdit);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Puts a profile's values in the form ({} removes the previous profile's untouched values)
  const apply = (incoming) => {
    const element = form();
    if (!element) return { filled: [], kept: [] };
    const fields = element.elements;
    const values = Object.fromEntries(Object.keys(AUTOFILL_FIELDS).map((name) => [name, fields[name]?.value ?? ""]));
    const plan = autofillPlan(values, filled.current, incoming);
    for (const [name, value] of Object.entries(plan.set)) if (fields[name]) fields[name].value = value;
    for (const name of Object.keys(AUTOFILL_FIELDS)) fields[name]?.classList.toggle("autofilled", name in plan.autofilled);
    filled.current = plan.autofilled;
    if ("company" in plan.set) onCompany(plan.set.company); // show other records for this company, as when typed
    // Apollo leads are outbound prospects: no welcome email unless the user ticks it again
    if (plan.filled.length && !welcome.current.touched && fields.welcome_email?.checked) {
      fields.welcome_email.checked = false;
      welcome.current.unticked = true;
      plan.unticked = true;
    }
    return plan;
  };

  const show = (answer) => {
    if (answer.status !== "matched" || answer.url_verified !== true) {
      apply({});
      if (answer.status === "no_match")
        return setStatus({ kind: "no_match", text: answer.message || "Apollo found no match for this profile." });
      return setStatus({ kind: "unverified", text: answer.message || "The profile could not be verified. Nothing was filled." });
    }
    const plan = apply(answer.fields);
    setStatus({ kind: "matched", filled: plan.filled, kept: plan.kept, unavailable: answer.unavailable || {}, unticked: plan.unticked });
  };

  const lookup = async (url) => {
    current.current = url;
    if (answers.current.has(url)) return show(answers.current.get(url));
    if (enabled.current === false) {
      apply({});
      return setStatus({ kind: "off" });
    }
    setStatus({ kind: "loading" });
    let request = pending.current.get(url);
    if (!request) {
      request = api.enrichLead(url);
      pending.current.set(url, request);
    }
    try {
      const answer = await request;
      answers.current.set(url, answer);
      if (alive.current && current.current === url) show(answer); // an older address's answer is never applied
    } catch (err) {
      if (!alive.current || current.current !== url) return;
      apply({});
      if (err.status === 503) {
        enabled.current = false;
        setStatus({ kind: "off" });
      } else setStatus({ kind: "error", text: err.message, url });
    } finally {
      pending.current.delete(url);
    }
  };

  const check = (value) => {
    clearTimeout(timer.current);
    if (!value.trim()) {
      current.current = "";
      apply({});
      return setStatus(enabled.current === false ? { kind: "off" } : { kind: "idle" });
    }
    const { url, error } = linkedInProfileUrl(value);
    if (error) {
      current.current = "";
      apply({});
      return setStatus({ kind: "invalid", text: error });
    }
    if (url !== current.current) lookup(url); // the same profile again: nothing new to do (Retry is explicit)
  };

  const input = (
    <input
      name="linkedin_url"
      type="text"
      required
      maxLength={300}
      defaultValue={defaultValue}
      placeholder="https://www.linkedin.com/in/name"
      aria-describedby={autofill ? "linkedin-autofill-help linkedin-autofill-status" : undefined}
      onPaste={autofill ? (event) => setTimeout(() => check(event.target.value), 0) : undefined}
      onChange={
        autofill
          ? (event) => {
              const value = event.target.value;
              clearTimeout(timer.current);
              timer.current = setTimeout(() => check(value), value.trim() ? TYPING_PAUSE : 0);
            }
          : undefined
      }
    />
  );
  return (
    <div className="linkedin-field">
      <label className="field">
        <span>
          LinkedIn Profile URL<i> *</i>
        </span>
        {input}
      </label>
      {autofill && (
        <>
          <small id="linkedin-autofill-help" className="field-hint">
            Paste a LinkedIn profile URL to autofill available lead details using Apollo.
          </small>
          <div id="linkedin-autofill-status" className={`autofill-status ${status.kind}`} aria-live="polite">
            {status.kind === "loading" && <p>Looking up this profile in Apollo…</p>}
            {status.kind === "off" && <p>LinkedIn autofill isn't available on this server. Fill in the lead details manually.</p>}
            {status.kind === "invalid" && <p className="autofill-problem">{status.text}</p>}
            {status.kind === "no_match" && <p>{status.text} Fill in the lead details manually.</p>}
            {status.kind === "unverified" && (
              <p className="autofill-problem" role="alert">
                <Icon name="warn" size={14} /> {status.text} Fill in the lead details manually.
              </p>
            )}
            {status.kind === "error" && (
              <p className="autofill-problem" role="alert">
                <Icon name="warn" size={14} /> {status.text}{" "}
                <button type="button" className="link" onClick={() => lookup(status.url)}>
                  Retry
                </button>
              </p>
            )}
            {status.kind === "matched" && (
              <>
                <p>
                  <Icon name="check" size={14} /> Profile URL verified.{" "}
                  {status.filled.length
                    ? `Filled by Apollo: ${names(status.filled)}. Check them before saving.`
                    : "Apollo found this profile; the fields already had your entries."}
                  {status.kept.length > 0 && ` Kept your entries for ${names(status.kept)}.`}
                  {status.unticked && " The welcome email was unticked (outbound prospect); tick it again if needed."}
                </p>
                {Object.keys(status.unavailable).length > 0 && (
                  <ul>
                    {Object.entries(status.unavailable).map(([name, reason]) => (
                      <li key={name}>
                        {AUTOFILL_FIELDS[name] || name}: {reason}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
