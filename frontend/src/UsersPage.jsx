// Users (Admin only): add users with a role, change roles, reset passwords, deactivate,
// and transfer someone's records to another user (e.g. when they leave).
// Also the "Change password" dialog every user can open from their profile menu.
import React, { useEffect, useState } from "react";
import { api } from "./api";
import { can } from "./permissions";
import { Avatar, Icon, ObjectIcon } from "./ui";

const ROLES = ["Salesperson", "Manager", "Admin"];
const ROLE_TEXT = {
  Salesperson: "Sees and changes only their own records",
  Manager: "Sees and changes the team's records, reassigns owners, gives team access",
  Admin: "Everything, plus managing users",
};

function Dialog({ title, subtitle, onClose, onSubmit, busy, error, submitLabel, children }) {
  useEffect(() => {
    const key = (e) => e.key === "Escape" && !busy && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [busy, onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className="modal small-modal" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={busy}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="dialog-title">{title}</h2>
        </header>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit(new FormData(e.currentTarget));
          }}
        >
          <div className="modal-body">
            {subtitle && <p className="modal-subtitle">{subtitle}</p>}
            {children}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="sf-button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="sf-button brand" disabled={busy} aria-busy={busy}>
              {busy ? "Saving…" : submitLabel}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

// Runs a save, keeps the dialog open with the error if it fails
function useSave(close, notify) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (work, message) => {
    setBusy(true);
    setError("");
    try {
      const result = await work();
      notify(typeof message === "function" ? message(result) : message);
      close(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, save };
}

const PASSWORD_HINT = "At least 8 characters, with letters and numbers.";

export function ChangePassword({ close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  const [mismatch, setMismatch] = useState("");
  return (
    <Dialog
      title="Change Password"
      onClose={close}
      busy={busy}
      error={mismatch || error}
      submitLabel="Change password"
      onSubmit={(form) => {
        if (form.get("new") !== form.get("confirm")) return setMismatch("The new passwords don't match.");
        setMismatch("");
        save(() => api.changePassword(form.get("current"), form.get("new")), "Your password was changed.");
      }}
    >
      <label className="field">
        <span>Current Password</span>
        <input type="password" name="current" autoComplete="current-password" required autoFocus />
      </label>
      <label className="field">
        <span>New Password</span>
        <input type="password" name="new" autoComplete="new-password" required minLength={8} />
      </label>
      <label className="field">
        <span>Confirm New Password</span>
        <input type="password" name="confirm" autoComplete="new-password" required />
      </label>
      <p className="login-hint">{PASSWORD_HINT}</p>
    </Dialog>
  );
}

// Which notifications also come by email (the bell always shows everything)
const EMAIL_SETTINGS = [
  ["email_stage_updates", "Stage changes", "When a lead or opportunity moves to a new stage"],
  ["email_assignments", "Assignments", "When a lead, opportunity or task is assigned to you"],
  ["email_reminders", "Reminders", "Upcoming tasks, demos and close dates, and overdue items"],
];

// My Profile: everyone can change their own name and email settings; email (username) and role are changed by the Admin
export function MyProfile({ user, close, notify, onSaved }) {
  const { busy, error, save } = useSave(close, notify);
  return (
    <Dialog
      title="My Profile"
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel="Save"
      onSubmit={(form) =>
        save(async () => {
          const updated = await api.updateProfile({
            full_name: form.get("full_name").trim(),
            ...Object.fromEntries(EMAIL_SETTINGS.map(([name]) => [name, form.get(name) === "on"])),
          });
          onSaved(updated);
          return updated;
        }, "Your profile was saved.")
      }
    >
      <label className="field">
        <span>
          Full Name <i>*</i>
        </span>
        <input name="full_name" defaultValue={user.full_name} required minLength={2} maxLength={100} autoFocus />
      </label>
      <label className="field">
        <span>Email (username)</span>
        <input value={user.email} readOnly />
      </label>
      <label className="field">
        <span>Role</span>
        <input value={user.role} readOnly />
      </label>
      <fieldset className="email-settings">
        <legend>Email Notifications</legend>
        {EMAIL_SETTINGS.map(([name, label, hint]) => (
          <label key={name} className="check-field">
            <input type="checkbox" name={name} defaultChecked={user[name] ?? name !== "email_stage_updates"} />
            <span>
              {label}
              <small>{hint}</small>
            </span>
          </label>
        ))}
        <p className="field-hint">All notifications appear in the notification bell.</p>
      </fieldset>
      <p className="login-hint">
        {user.role === "Admin"
          ? "To change your email, go to Users and click Edit on your row."
          : "To change your email or role, contact your Admin."}
      </p>
    </Dialog>
  );
}

function EditUser({ target, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  return (
    <Dialog
      title={`Edit User: ${target.full_name}`}
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel="Save"
      onSubmit={(form) =>
        save(
          () => api.updateUser(target.id, { full_name: form.get("full_name").trim(), email: form.get("email").trim() }),
          (u) => `${u.full_name} was updated.`,
        )
      }
    >
      <label className="field">
        <span>
          Full Name <i>*</i>
        </span>
        <input name="full_name" defaultValue={target.full_name} required minLength={2} maxLength={100} autoFocus />
      </label>
      <label className="field">
        <span>
          Email (username) <i>*</i>
        </span>
        <input name="email" type="email" defaultValue={target.email} required autoComplete="off" />
      </label>
    </Dialog>
  );
}

function NewUser({ close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  return (
    <Dialog
      title="New User"
      subtitle="They get an email with their username, this password and the link to log in. They can change the password after logging in."
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel="Add user"
      onSubmit={(form) =>
        save(
          () => api.createUser(Object.fromEntries(form)),
          (user) => `${user.full_name} was added as ${user.role}.`,
        )
      }
    >
      <div className="form-grid">
        <label className="field">
          <span>
            Full Name <i>*</i>
          </span>
          <input name="full_name" required minLength={2} maxLength={100} autoFocus />
        </label>
        <label className="field">
          <span>
            Email (username) <i>*</i>
          </span>
          <input name="email" type="email" required autoComplete="off" />
        </label>
        <label className="field">
          <span>
            Role <i>*</i>
          </span>
          <select name="role" defaultValue="Salesperson" required>
            {ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>
            Password <i>*</i>
          </span>
          <input name="password" type="text" required minLength={8} autoComplete="off" />
        </label>
      </div>
      <p className="login-hint">{PASSWORD_HINT}</p>
    </Dialog>
  );
}

function ResetPassword({ target, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  return (
    <Dialog
      title={`Reset Password: ${target.full_name}`}
      subtitle="The new password is emailed to the user."
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel="Reset password"
      onSubmit={(form) => save(() => api.resetPassword(target.id, form.get("password")), `Password reset for ${target.full_name}.`)}
    >
      <label className="field">
        <span>
          New Password <i>*</i>
        </span>
        <input name="password" type="text" required minLength={8} autoComplete="off" autoFocus />
      </label>
      <p className="login-hint">{PASSWORD_HINT}</p>
    </Dialog>
  );
}

function Transfer({ target, users, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  const others = users.filter((u) => u.is_active && u.id !== target.id);
  return (
    <Dialog
      title={`Transfer Records: ${target.full_name}`}
      subtitle="Open leads, open opportunities, accounts, contacts and open tasks move to the new owner. Won, lost and converted records keep their history."
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel="Transfer"
      onSubmit={(form) =>
        save(
          () => api.transferRecords(target.id, form.get("to"), form.get("deactivate") === "on"),
          (r) => `${r.total} record${r.total === 1 ? "" : "s"} moved${r.deactivated ? ` and ${target.full_name} was deactivated` : ""}.`,
        )
      }
    >
      <label className="field">
        <span>
          New Owner <i>*</i>
        </span>
        <select name="to" required defaultValue="">
          <option value="">Select a user</option>
          {others.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name} ({u.role})
            </option>
          ))}
        </select>
      </label>
      <label className="check-field">
        <input type="checkbox" name="deactivate" defaultChecked={target.is_active} /> Also deactivate {target.full_name} (they can't log in)
      </label>
    </Dialog>
  );
}

export default function UsersPage({ user, data, reload, notify, onSelfChanged }) {
  const admin = can(user, "manage_users"); // Managers see this page only to give team access
  const [users, setUsers] = useState(null);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState(null); // {type: "new" | "edit" | "reset" | "transfer", target}
  const [busyId, setBusyId] = useState(null);
  const load = () =>
    api
      .allUsers()
      .then((list) => {
        setUsers(list);
        setError("");
      })
      .catch((err) => setError(err.message));
  useEffect(() => {
    load();
  }, []);

  const owned = (id) =>
    data.leads.filter((r) => r.owner_id === id && ["New", "Nurturing", "Demo"].includes(r.stage)).length +
    data.opportunities.filter((r) => r.owner_id === id && ["Opportunity", "Proposal"].includes(r.stage)).length;

  const change = async (target, changes, message) => {
    setBusyId(target.id);
    try {
      await api.updateUser(target.id, changes);
      notify(message);
      await load();
      reload().catch(() => {});
    } catch (err) {
      notify(err.message);
    } finally {
      setBusyId(null);
    }
  };
  const teamAccess = async (target, value) => {
    setBusyId(target.id);
    try {
      await api.setTeamAccess(target.id, value);
      notify(value ? `${target.full_name} can now see the whole team's records.` : `${target.full_name} now sees only their own records.`);
      await load();
    } catch (err) {
      notify(err.message);
    } finally {
      setBusyId(null);
    }
  };
  const closeDialog = (result) => {
    setDialog(null);
    if (result?.id === user.id && result.email) onSelfChanged?.(result); // the Admin edited their own name / email
    if (result) {
      load();
      reload().catch(() => {});
    }
  };

  return (
    <div className="page">
      <section className="list-header card">
        <div className="list-title">
          <ObjectIcon type="contact" size={36} />
          <div>
            <small>Setup</small>
            <h1>Users</h1>
          </div>
          {admin && (
            <div className="list-buttons">
              <button className="sf-button brand" onClick={() => setDialog({ type: "new" })}>
                New User
              </button>
            </div>
          )}
        </div>
        <ul className="role-legend">
          {ROLES.map((r) => (
            <li key={r}>
              <b>{r}:</b> {ROLE_TEXT[r]}
            </li>
          ))}
        </ul>
      </section>
      {error && (
        <div className="alert" role="alert">
          <Icon name="warn" size={16} />
          <span>{error}</span>
        </div>
      )}
      <section className="card table-card">
        <div className="table-scroll">
          <table className="sf-table users-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>Team Access</th>
                <th className="num">Open Records</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {(users || []).map((u) => {
                const self = u.id === user.id;
                return (
                  <tr key={u.id} className={u.is_active ? "" : "inactive"}>
                    <td>
                      <span className="user-cell">
                        <Avatar name={u.full_name} size={28} />
                        {u.full_name}
                        {self && <small>(you)</small>}
                      </span>
                    </td>
                    <td>{u.email}</td>
                    <td>
                      <select
                        aria-label={`Role of ${u.full_name}`}
                        value={u.role}
                        disabled={!admin || self || busyId === u.id}
                        title={self ? "You can't change your own role" : undefined}
                        onChange={(e) => change(u, { role: e.target.value }, `${u.full_name} is now ${e.target.value}.`)}
                      >
                        {ROLES.map((r) => (
                          <option key={r}>{r}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <span className={`pill ${u.is_active ? "pill-ok" : "pill-off"}`}>{u.is_active ? "Active" : "Inactive"}</span>
                    </td>
                    <td>
                      {u.role === "Salesperson" ? (
                        <label className="switch" title="Let this salesperson see the whole team's records (view only)">
                          <input
                            type="checkbox"
                            checked={!!u.team_access}
                            disabled={!can(user, "grant_team_access") || busyId === u.id}
                            onChange={(e) => teamAccess(u, e.target.checked)}
                            aria-label={`Team access for ${u.full_name}`}
                          />
                          <span>{u.team_access ? "Whole team" : "Own records"}</span>
                        </label>
                      ) : (
                        <span className="muted">Whole team</span>
                      )}
                    </td>
                    <td className="num">{owned(u.id)}</td>
                    <td>
                      {admin && (
                      <span className="row-actions">
                        <button className="sf-button small" onClick={() => setDialog({ type: "edit", target: u })}>
                          Edit
                        </button>
                        <button className="sf-button small" onClick={() => setDialog({ type: "reset", target: u })}>
                          Reset Password
                        </button>
                        <button className="sf-button small" onClick={() => setDialog({ type: "transfer", target: u })}>
                          Transfer Records
                        </button>
                        {!self && (
                          <button
                            className="sf-button small"
                            disabled={busyId === u.id}
                            onClick={() =>
                              change(
                                u,
                                { is_active: !u.is_active },
                                `${u.full_name} was ${u.is_active ? "deactivated" : "activated"}.`,
                              )
                            }
                          >
                            {u.is_active ? "Deactivate" : "Activate"}
                          </button>
                        )}
                      </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {users === null && !error && <p className="table-empty">Loading…</p>}
        </div>
      </section>
      {dialog?.type === "new" && <NewUser close={closeDialog} notify={notify} />}
      {dialog?.type === "edit" && <EditUser target={dialog.target} close={closeDialog} notify={notify} />}
      {dialog?.type === "reset" && <ResetPassword target={dialog.target} close={closeDialog} notify={notify} />}
      {dialog?.type === "transfer" && <Transfer target={dialog.target} users={users || []} close={closeDialog} notify={notify} />}
    </div>
  );
}
