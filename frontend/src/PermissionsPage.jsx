// Permissions tab of Manage Access: which role can do what. Rows are permissions (in sections), columns are roles.
// Changes are collected first and applied with Save. The Admin column is locked so nobody can lock themselves out.
import React, { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { dateTime } from "./format";
import { Icon } from "./ui";

const ROLE_ORDER = ["Admin", "Manager", "Salesperson"];

export default function PermissionsTab({ notify }) {
  const [matrix, setMatrix] = useState(null);
  const [draft, setDraft] = useState({}); // "permission:role" -> allowed, only cells changed and not yet saved
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const load = () =>
    api
      .permissions()
      .then((m) => {
        setMatrix(m);
        setDraft({});
        setError("");
      })
      .catch((err) => setError(err.message));
  useEffect(() => {
    load();
  }, []);

  const roles = matrix ? ROLE_ORDER.filter((r) => matrix.roles.includes(r)) : [];
  const groups = useMemo(() => {
    const out = [];
    for (const p of matrix?.permissions || []) {
      let g = out.find((x) => x.name === p.group);
      if (!g) out.push((g = { name: p.group, rows: [] }));
      g.rows.push(p);
    }
    return out;
  }, [matrix]);

  const key = (p, role) => `${p.key}:${role}`;
  const value = (p, role) => (key(p, role) in draft ? draft[key(p, role)] : p.roles[role].allowed);
  const set = (p, role, allowed) => {
    const next = { ...draft };
    if (allowed === p.roles[role].allowed) delete next[key(p, role)];
    else next[key(p, role)] = allowed;
    setDraft(next);
  };
  const total = matrix?.permissions.length || 0;
  const countFor = (role) => (matrix?.permissions || []).filter((p) => value(p, role)).length;
  const resetRole = (role) => {
    const next = { ...draft };
    for (const p of matrix.permissions) {
      const d = p.roles[role].default;
      if (d === p.roles[role].allowed) delete next[key(p, role)];
      else next[key(p, role)] = d;
    }
    setDraft(next);
  };
  const changes = Object.keys(draft).length;

  const save = async () => {
    setSaving(true);
    try {
      for (const [k, allowed] of Object.entries(draft)) {
        const [permission, role] = k.split(":");
        await api.setPermission(role, permission, allowed);
      }
      notify(`${changes} permission change${changes === 1 ? "" : "s"} saved. They apply the next time each user opens a page.`);
      await load();
    } catch (err) {
      notify(err.message);
      await load();
    } finally {
      setSaving(false);
    }
  };

  if (error)
    return (
      <div className="alert" role="alert">
        <Icon name="warn" size={16} />
        <span>{error}</span>
      </div>
    );
  if (!matrix) return <p className="table-empty">Loading…</p>;

  return (
    <div className="perm-tab">
      <div className="table-scroll">
        <table className="sf-table perm-table">
          <thead>
            <tr>
              <th>Permission</th>
              {roles.map((role) => (
                <th key={role} className="perm-role">
                  {role}
                  <small>
                    {countFor(role)} of {total}
                  </small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <React.Fragment key={g.name}>
                <tr className="perm-group">
                  <th colSpan={roles.length + 1} scope="colgroup">
                    {g.name}
                  </th>
                </tr>
                {g.rows.map((p) => (
                  <tr key={p.key}>
                    <td>
                      <b>{p.label}</b>
                      <small>{p.description}</small>
                    </td>
                    {roles.map((role) => {
                      const cell = p.roles[role];
                      const changed = key(p, role) in draft;
                      const title = cell.locked
                        ? "The Admin role always has every permission"
                        : cell.changed_by
                          ? `Last changed by ${cell.changed_by}, ${dateTime(cell.changed_at)}`
                          : undefined;
                      return (
                        <td key={role} className={`perm-cell ${cell.locked ? "locked" : ""} ${changed ? "changed" : ""}`} title={title}>
                          <input
                            type="checkbox"
                            checked={value(p, role)}
                            disabled={cell.locked || saving}
                            onChange={(e) => set(p, role, e.target.checked)}
                            aria-label={`${p.label} for ${role}`}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </React.Fragment>
            ))}
            <tr className="perm-reset">
              <td>Reset to defaults</td>
              {roles.map((role) => (
                <td key={role} className="perm-cell">
                  {role === "Admin" ? (
                    <span className="muted">—</span>
                  ) : (
                    <button className="link" onClick={() => resetRole(role)} disabled={saving}>
                      Reset
                    </button>
                  )}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="perm-note">Greyed-out cells are locked: the Admin role always has every permission.</p>
      <div className="perm-actions">
        <button className="sf-button" onClick={() => setDraft({})} disabled={!changes || saving}>
          Discard
        </button>
        <button className="sf-button brand" onClick={save} disabled={!changes || saving} aria-busy={saving}>
          {saving ? "Saving…" : changes ? `Save ${changes} change${changes === 1 ? "" : "s"}` : "Save"}
        </button>
      </div>
    </div>
  );
}
