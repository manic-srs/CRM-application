// Roles & Permissions (Admin): which role can do what. Rows are permissions, columns are roles.
// The Admin column is locked so nobody can lock themselves out. Every change is saved with who made it.
import React, { useEffect, useState } from "react";
import { api } from "./api";
import { dateTime } from "./format";
import { Icon, ObjectIcon } from "./ui";

export default function PermissionsPage({ notify }) {
  const [matrix, setMatrix] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const load = () =>
    api
      .permissions()
      .then((m) => {
        setMatrix(m);
        setError("");
      })
      .catch((err) => setError(err.message));
  useEffect(() => {
    load();
  }, []);

  const toggle = async (permission, role, allowed) => {
    const key = `${permission.key}:${role}`;
    setBusy(key);
    try {
      const res = await api.setPermission(role, permission.key, allowed);
      notify(res.message);
      await load();
    } catch (err) {
      notify(err.message);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="page">
      <section className="list-header card">
        <div className="list-title">
          <ObjectIcon type="contact" size={36} />
          <div>
            <small>Setup</small>
            <h1>Roles &amp; Permissions</h1>
          </div>
        </div>
        <p className="muted perm-intro">
          Choose what each role can do. Changes apply the next time the user opens a page. Admin permissions can't be
          changed. A Manager can also give team access to a single salesperson on the Users page.
        </p>
      </section>
      {error && (
        <div className="alert" role="alert">
          <Icon name="warn" size={16} />
          <span>{error}</span>
        </div>
      )}
      {matrix && (
        <section className="card table-card">
          <div className="table-scroll">
            <table className="sf-table perm-table">
              <thead>
                <tr>
                  <th>Permission</th>
                  {matrix.roles.map((role) => (
                    <th key={role} className="perm-role">
                      {role}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.permissions.map((p) => (
                  <tr key={p.key}>
                    <td>
                      <b>{p.label}</b>
                      <small>{p.description}</small>
                    </td>
                    {matrix.roles.map((role) => {
                      const cell = p.roles[role];
                      const id = `${p.key}-${role}`;
                      return (
                        <td key={role} className="perm-cell">
                          <label htmlFor={id} className={`perm-check ${cell.allowed ? "on" : ""}`}>
                            <input
                              id={id}
                              type="checkbox"
                              checked={cell.allowed}
                              disabled={cell.locked || busy === `${p.key}:${role}`}
                              onChange={(e) => toggle(p, role, e.target.checked)}
                              aria-label={`${p.label} for ${role}`}
                            />
                            {cell.locked && <Icon name="lock" size={12} />}
                          </label>
                          {cell.changed_by && (
                            <small className="perm-changed" title={dateTime(cell.changed_at)}>
                              by {cell.changed_by}
                            </small>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
