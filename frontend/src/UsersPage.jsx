// Manage Access: People (add users, reset passwords, transfer leads, record access, deactivate)
// and Permissions (what each role can do). The Admin can change a user's role later; role and access changes
// are saved with the date and time in the Activity Log.
// Also the "Change password" and "My Profile" dialogs every user can open from their profile menu.
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { can } from "./permissions";
import PermissionsTab from "./PermissionsPage";
import { dateTime } from "./format";
import { Avatar, Icon, Pagination, usePaged } from "./ui";

const ROLES = ["Admin", "Manager", "Salesperson"];

// A random temporary password with letters and numbers (no look-alike characters)
const generatePassword = () => {
  const letters = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ";
  const digits = "23456789";
  const pick = (set, n) => Array.from(crypto.getRandomValues(new Uint32Array(n)), (x) => set[x % set.length]).join("");
  return pick(letters, 4) + pick(digits, 3) + pick(letters, 3);
};

// Temporary password field with Generate and Copy, used when adding a user and resetting a password
function PasswordField({ label, autoFocus }) {
  const [value, setValue] = useState("");
  const [copied, setCopied] = useState(false);
  return (
    <div className="field">
      <span>
        {label} <i>*</i>
      </span>
      <div className="password-row">
        <input
          name="password"
          type="text"
          required
          minLength={8}
          autoComplete="off"
          autoFocus={autoFocus}
          value={value}
          onChange={(e) => (setValue(e.target.value), setCopied(false))}
        />
        <button type="button" className="sf-button small" onClick={() => (setValue(generatePassword()), setCopied(false))}>
          Generate
        </button>
        <button
          type="button"
          className="sf-button small"
          disabled={!value}
          onClick={() => navigator.clipboard?.writeText(value).then(() => setCopied(true)).catch(() => {})}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

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
          ? "To change your email, open Manage Access and edit your user."
          : "To change your email or role, contact your Admin."}
      </p>
    </Dialog>
  );
}

function EditUser({ target, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  return (
    <Dialog
      title={`Edit ${target.full_name}`}
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel="Save"
      onSubmit={(form) =>
        save(
          () =>
            api.updateUser(target.id, {
              full_name: form.get("full_name").trim(),
              email: form.get("email").trim(),
              role: form.get("role"),
            }),
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
      <label className="field">
        <span>
          Role <i>*</i>
        </span>
        <select name="role" defaultValue={target.role} required>
          {ROLES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        <small className="field-hint">
          {target.role_changed_at ? `Role last changed ${dateTime(target.role_changed_at)}. ` : ""}
          The user is notified, and the change is saved in the Activity Log.
        </small>
      </label>
    </Dialog>
  );
}

function NewUser({ close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  return (
    <Dialog
      title="Add User"
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
      <label className="field">
        <span>
          Full Name <i>*</i>
        </span>
        <input name="full_name" required minLength={2} maxLength={100} autoFocus />
      </label>
      <label className="field">
        <span>
          Email <i>*</i>
        </span>
        <input name="email" type="email" required autoComplete="off" placeholder="name@srsconsultinginc.com" />
      </label>
      <PasswordField label="Temporary Password" />
      <p className="field-hint">{PASSWORD_HINT} It's emailed to the user, who can change it after signing in.</p>
      <label className="field">
        <span>
          Role <i>*</i>
        </span>
        <select name="role" defaultValue="" required>
          <option value="" disabled>
            Choose a role
          </option>
          {ROLES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        <small className="field-hint">The Admin can change the role later from Edit.</small>
      </label>
    </Dialog>
  );
}

function ResetPassword({ target, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  return (
    <Dialog
      title={`Reset Password for ${target.full_name}`}
      subtitle="The new password is emailed to the user."
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel="Reset password"
      onSubmit={(form) => save(() => api.resetPassword(target.id, form.get("password")), `Password reset for ${target.full_name}.`)}
    >
      <PasswordField label="New Password" autoFocus />
      <p className="field-hint">{PASSWORD_HINT}</p>
    </Dialog>
  );
}

function Transfer({ target, users, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  const others = users.filter((u) => u.is_active && u.id !== target.id);
  return (
    <Dialog
      title={`Transfer Leads from ${target.full_name}`}
      subtitle="Their open leads move to the new owner, together with their open opportunities, accounts, contacts and open tasks. Won, lost and converted leads keep their history."
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel="Transfer"
      onSubmit={(form) =>
        save(
          () => api.transferRecords(target.id, form.get("to"), form.get("deactivate") === "on"),
          (r) => `Leads transferred (${r.total} item${r.total === 1 ? "" : "s"} moved)${r.deactivated ? ` and ${target.full_name} was deactivated` : ""}.`,
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

const MoreIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
    <circle cx="5" cy="12" r="2" />
    <circle cx="12" cy="12" r="2" />
    <circle cx="19" cy="12" r="2" />
  </svg>
);

// The "⋯" actions menu of one user row
function RowMenu({ label, items }) {
  const [open, setOpen] = useState(null); // where the menu opens (fixed position, so the table can't clip it)
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const away = (e) => ref.current && !ref.current.contains(e.target) && setOpen(null);
    const key = (e) => e.key === "Escape" && setOpen(null);
    const close = () => setOpen(null);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);
  if (!items.length) return <span className="muted">—</span>;
  return (
    <div className="row-menu" ref={ref}>
      <button className="icon-button" aria-label={label} aria-haspopup="menu" aria-expanded={!!open}
        onClick={(e) => {
          if (open) return setOpen(null);
          const r = e.currentTarget.getBoundingClientRect();
          const below = window.innerHeight - r.bottom > 260;
          setOpen(below ? { top: r.bottom + 4, right: window.innerWidth - r.right } : { bottom: window.innerHeight - r.top + 4, right: window.innerWidth - r.right });
        }}
      >
        <MoreIcon />
      </button>
      {open && (
        <div className="row-menu-list" role="menu" style={open}>
          {items.map((item, i) =>
            item === "-" ? (
              <hr key={i} />
            ) : (
              <button
                key={item.label}
                role="menuitem"
                className={item.danger ? "danger" : ""}
                onClick={() => {
                  setOpen(null);
                  item.onClick();
                }}
              >
                {item.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

function accessOf(u) {
  if (u.role !== "Salesperson") return { label: "All records", tone: "all" };
  return u.team_access ? { label: "Team records (view only)", tone: "team" } : { label: "Own records", tone: "own" };
}

function PeopleTab({ user, data, reload, notify, onSelfChanged }) {
  const admin = can(user, "manage_users"); // Managers use this tab only to give salespeople team access
  const [users, setUsers] = useState(null);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState(null); // {type: "new" | "edit" | "reset" | "transfer", target}
  const [roleFilter, setRoleFilter] = useState("All");
  const [status, setStatus] = useState("any");
  const [query, setQuery] = useState("");
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

  // Open Leads: leads this user owns that are still New, Nurturing or Demo
  const owned = (id) => data.leads.filter((r) => r.owner_id === id && ["New", "Nurturing", "Demo"].includes(r.stage)).length;

  const run = async (work, message) => {
    try {
      await work();
      notify(message);
      await load();
      reload().catch(() => {});
    } catch (err) {
      notify(err.message);
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

  const list = users || [];
  const count = (role) => list.filter((u) => role === "All" || u.role === role).length;
  const q = query.trim().toLowerCase();
  const shown = list.filter(
    (u) =>
      (roleFilter === "All" || u.role === roleFilter) &&
      (status === "any" || (status === "active") === u.is_active) &&
      (!q || u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)),
  );
  const peoplePage = usePaged(shown, `${roleFilter}|${query}|${status}`);

  const actions = (u) => {
    const self = u.id === user.id;
    const items = [];
    if (admin) {
      items.push(
        { label: "Edit details", onClick: () => setDialog({ type: "edit", target: u }) },
        { label: "Reset password", onClick: () => setDialog({ type: "reset", target: u }) },
        { label: "Transfer leads", onClick: () => setDialog({ type: "transfer", target: u }) },
      );
    }
    if (u.role === "Salesperson" && u.is_active && can(user, "grant_team_access")) {
      if (items.length) items.push("-");
      items.push(
        u.team_access
          ? {
              label: "Remove team access",
              onClick: () => run(() => api.setTeamAccess(u.id, false), `${u.full_name} now sees only their own records.`),
            }
          : {
              label: "Give team access",
              onClick: () => run(() => api.setTeamAccess(u.id, true), `${u.full_name} can now view the whole team's records.`),
            },
      );
    }
    if (admin && !self) {
      items.push("-", {
        label: u.is_active ? "Deactivate" : "Activate",
        danger: u.is_active,
        onClick: () =>
          run(() => api.updateUser(u.id, { is_active: !u.is_active }), `${u.full_name} was ${u.is_active ? "deactivated" : "activated"}.`),
      });
    }
    return items;
  };

  return (
    <>
      <div className="role-cards" role="tablist" aria-label="Filter by role">
        {["All", ...ROLES].map((role) => (
          <button
            key={role}
            role="tab"
            aria-selected={roleFilter === role}
            className={`role-card ${roleFilter === role ? "on" : ""}`}
            onClick={() => setRoleFilter(role)}
          >
            <span>{role === "All" ? "All users" : role}</span>
            <b>{users ? count(role) : "–"}</b>
          </button>
        ))}
      </div>
      <div className="people-toolbar">
        <label className="search-field">
          <Icon name="search" size={15} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name or email" aria-label="Search users" />
        </label>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="any">Any status</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
        {admin && (
          <button className="sf-button brand" onClick={() => setDialog({ type: "new" })}>
            Add User
          </button>
        )}
      </div>
      {error && (
        <div className="alert" role="alert">
          <Icon name="warn" size={16} />
          <span>{error}</span>
        </div>
      )}
      <div className="table-scroll">
        <table className="sf-table users-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Record Access</th>
              <th>Status</th>
              <th className="num">Open Leads</th>
              <th className="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {peoplePage.pageRows.map((u) => {
              const access = accessOf(u);
              return (
                <tr key={u.id} className={u.is_active ? "" : "inactive"}>
                  <td>
                    <span className="user-cell">
                      <Avatar name={u.full_name} size={32} />
                      <span className="user-text">
                        <b>
                          {u.full_name} {u.id === user.id && <small>(you)</small>}
                        </b>
                        <small>{u.email}</small>
                      </span>
                    </span>
                  </td>
                  <td>{u.role}</td>
                  <td>
                    <span className={`access-badge ${access.tone}`}>{access.label}</span>
                  </td>
                  <td>
                    <span className={`pill ${u.is_active ? "pill-ok" : "pill-off"}`}>{u.is_active ? "Active" : "Inactive"}</span>
                  </td>
                  <td className="num">{owned(u.id)}</td>
                  <td className="actions-col">
                    <RowMenu label={`Actions for ${u.full_name}`} items={actions(u)} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {users === null && !error && <p className="table-empty">Loading…</p>}
        {users && !shown.length && <p className="table-empty">No users match.</p>}
      </div>
      <Pagination {...peoplePage.pager} />
      {dialog?.type === "new" && <NewUser close={closeDialog} notify={notify} />}
      {dialog?.type === "edit" && <EditUser target={dialog.target} close={closeDialog} notify={notify} />}
      {dialog?.type === "reset" && <ResetPassword target={dialog.target} close={closeDialog} notify={notify} />}
      {dialog?.type === "transfer" && <Transfer target={dialog.target} users={list} close={closeDialog} notify={notify} />}
    </>
  );
}

// Activity Log tab: who added or changed users, permissions and record owners (newest first)
function ActivityTab() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    api.activityLog().then(setRows).catch((err) => setError(err.message));
  }, []);
  const q = query.trim().toLowerCase();
  const shown = (rows || []).filter((r) => !q || [r.by, r.action, r.target, r.details].join(" ").toLowerCase().includes(q));
  const { pageRows, pager } = usePaged(shown, q);
  return (
    <>
      <div className="people-toolbar">
        <label className="search-field">
          <Icon name="search" size={15} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by user, action or record" aria-label="Search activity" />
        </label>
      </div>
      {error && (
        <div className="alert" role="alert">
          <Icon name="warn" size={16} />
          <span>{error}</span>
        </div>
      )}
      <div className="table-scroll">
        <table className="sf-table users-table activity-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Done By</th>
              <th>Action</th>
              <th>Record</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{dateTime(r.at)}</td>
                <td>{r.by}</td>
                <td>
                  <b>{r.action}</b>
                </td>
                <td>{r.target}</td>
                <td className="muted">{r.details || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows === null && !error && <p className="table-empty">Loading…</p>}
        {rows && !shown.length && <p className="table-empty">{rows.length ? "No activity matches." : "No activity yet."}</p>}
      </div>
      <Pagination {...pager} />
    </>
  );
}

// Manage Access page: People, Permissions and Activity Log tabs (#/users, #/permissions, #/activity)
export default function ManageAccess({ tab = "people", user, data, reload, notify, onSelfChanged }) {
  const tabs = [
    ["people", "People", "#/users", true],
    ["permissions", "Permissions", "#/permissions", can(user, "manage_permissions")],
    ["activity", "Activity Log", "#/activity", can(user, "manage_users")],
  ].filter((t) => t[3]);
  const current = tabs.some((t) => t[0] === tab) ? tab : "people";
  return (
    <div className="page">
      <section className="card access-card">
        <header className="access-header">
          <h1>Manage Access</h1>
          <p>Add users, set their record access, and choose what each role can do.</p>
        </header>
        {tabs.length > 1 && (
          <nav className="access-tabs" aria-label="Manage Access">
            {tabs.map(([key, label, href]) => (
              <a key={key} href={href} className={current === key ? "on" : ""} aria-current={current === key ? "page" : undefined}>
                {label}
              </a>
            ))}
          </nav>
        )}
        {current === "people" && <PeopleTab user={user} data={data} reload={reload} notify={notify} onSelfChanged={onSelfChanged} />}
        {current === "permissions" && <PermissionsTab notify={notify} />}
        {current === "activity" && <ActivityTab />}
      </section>
    </div>
  );
}
