// Manage Access: People (add users, reset passwords, transfer leads, record access, deactivate)
// and Permissions (what each role can do). The Admin can change a user's role later; role and access changes
// are saved with the date and time in the Activity Log.
// Also the "Change password" and "My Profile" dialogs every user can open from their profile menu.
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { LEAD_OPEN_STAGES } from "./domain";
import { UploadUsers } from "./LeadFiles";
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

// "Reports To": the Manager a Salesperson works for (their team). Only Salespeople report to a Manager.
function ReportsToField({ managers, defaultValue, name = "reports_to_id" }) {
  return (
    <label className="field">
      <span>Reports To (Manager)</span>
      <select name={name} defaultValue={defaultValue || ""}>
        <option value="">No Manager</option>
        {managers.map((m) => (
          <option key={m.id} value={m.id}>
            {m.full_name}
          </option>
        ))}
      </select>
      <small className="field-hint">The Manager adds and deactivates the people in their team and sees their activity.</small>
    </label>
  );
}

function EditUser({ target, managers, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  const [role, setRole] = useState(target.role);
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
              ...(form.get("role") === "Salesperson" ? { reports_to_id: Number(form.get("reports_to_id") || 0) } : {}),
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
        <select name="role" value={role} onChange={(e) => setRole(e.target.value)} required>
          {ROLES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        <small className="field-hint">
          {target.role_changed_at ? `Role last changed ${dateTime(target.role_changed_at)}. ` : ""}
          The user is notified, and the change is saved in the Activity Log.
        </small>
      </label>
      {role === "Salesperson" && (
        <ReportsToField managers={managers.filter((m) => m.id !== target.id)} defaultValue={target.reports_to_id} />
      )}
    </Dialog>
  );
}

// Admin: any role, and the Manager of a Salesperson. Manager (Manage own team): a Salesperson in their own team.
function NewUser({ admin, me, managers, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  const [role, setRole] = useState(admin ? "" : "Salesperson");
  return (
    <Dialog
      title={admin ? "Add User" : "Add Salesperson"}
      subtitle={admin ? undefined : `They join your team (Reports To: ${me.full_name}).`}
      onClose={() => close()}
      busy={busy}
      error={error}
      submitLabel={admin ? "Add user" : "Add salesperson"}
      onSubmit={(form) =>
        save(
          () => api.createUser(Object.fromEntries(form)),
          (user) => `${user.full_name} was added as ${user.role}${user.reports_to_name ? ` in ${user.reports_to_name}'s team` : ""}.`,
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
      {admin ? (
        <>
          <label className="field">
            <span>
              Role <i>*</i>
            </span>
            <select name="role" value={role} onChange={(e) => setRole(e.target.value)} required>
              <option value="" disabled>
                Choose a role
              </option>
              {ROLES.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            <small className="field-hint">The Admin can change the role later from Edit.</small>
          </label>
          {role === "Salesperson" && <ReportsToField managers={managers} />}
        </>
      ) : (
        <input type="hidden" name="role" value="Salesperson" />
      )}
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

function Transfer({ target, users, admin, me, close, notify }) {
  const { busy, error, save } = useSave(close, notify);
  // a Manager moves records only to themselves or someone in their team
  const others = users.filter(
    (u) => u.is_active && u.id !== target.id && (admin || u.id === me.id || u.reports_to_id === me.id),
  );
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
  const admin = can(user, "manage_users");
  const manager = !admin && can(user, "manage_team"); // adds and deactivates the Salespeople in their own team
  const [users, setUsers] = useState(null);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState(null); // {type: "new" | "edit" | "reset" | "transfer", target}
  const [roleFilter, setRoleFilter] = useState("All");
  const [team, setTeam] = useState(manager ? "mine" : "all"); // Managers: My team / All Salespeople
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

  // Open Leads: leads this user owns that are still open (not Converted or Lost)
  const owned = (id) => data.leads.filter((r) => r.owner_id === id && LEAD_OPEN_STAGES.includes(r.stage)).length;

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
  const managers = list.filter((u) => u.role === "Manager" && u.is_active);
  const inMyTeam = (u) => u.reports_to_id === user.id;
  // Admins see everyone; Managers see the Salespeople (their own team first)
  const base = admin ? list : list.filter((u) => u.role === "Salesperson");
  const count = (role) => base.filter((u) => role === "All" || u.role === role).length;
  const q = query.trim().toLowerCase();
  const shown = base.filter(
    (u) =>
      (!admin || roleFilter === "All" || u.role === roleFilter) &&
      (admin || team === "all" || inMyTeam(u)) &&
      (status === "any" || (status === "active") === u.is_active) &&
      (!q || u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)),
  );
  const peoplePage = usePaged(shown, `${roleFilter}|${team}|${query}|${status}`);

  const actions = (u) => {
    const self = u.id === user.id;
    const mine = manager && inMyTeam(u);
    const items = [];
    if (admin) {
      items.push(
        { label: "Edit details", onClick: () => setDialog({ type: "edit", target: u }) },
        { label: "Reset password", onClick: () => setDialog({ type: "reset", target: u }) },
        { label: "Transfer leads", onClick: () => setDialog({ type: "transfer", target: u }) },
      );
    } else if (mine) {
      items.push({ label: "Transfer leads", onClick: () => setDialog({ type: "transfer", target: u }) });
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
    if ((admin || mine) && !self) {
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
      {/* Role cards (Admin) or team cards (Manager): click one to filter the list */}
      <div className={`role-cards ${admin ? "" : "two"}`} role="tablist" aria-label={admin ? "Filter by role" : "Filter by team"}>
        {(admin
          ? ["All", ...ROLES].map((role) => [role, role === "All" ? "All users" : role, count(role), roleFilter === role, () => setRoleFilter(role)])
          : [
              ["mine", "My team", list.filter(inMyTeam).length, team === "mine", () => setTeam("mine")],
              ["all", "All Salespeople", base.length, team === "all", () => setTeam("all")],
            ]
        ).map(([key, label, n, on, pick]) => (
          <button key={key} role="tab" aria-selected={on} className={`role-card ${on ? "on" : ""}`} onClick={pick}>
            <span>{label}</span>
            <b>{users ? n : "–"}</b>
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
          <button className="sf-button" onClick={() => setDialog({ type: "upload" })} title="Add many users from Excel or CSV">
            Upload Users
          </button>
        )}
        {(admin || manager) && (
          <button className="sf-button brand" onClick={() => setDialog({ type: "new" })}>
            {admin ? "Add User" : "Add Salesperson"}
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
              <th>Reports To</th>
              <th>Record Access</th>
              <th>Status</th>
              <th className="num">Open Leads</th>
              <th className="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {peoplePage.pageRows.map((u) => {
              const access = accessOf(u);
              const items = actions(u);
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
                  <td>{u.reports_to_name || <span className="muted">—</span>}</td>
                  <td>
                    <span className={`access-badge ${access.tone}`}>{access.label}</span>
                  </td>
                  <td>
                    <span className={`pill ${u.is_active ? "pill-ok" : "pill-off"}`}>{u.is_active ? "Active" : "Inactive"}</span>
                  </td>
                  <td className="num">{owned(u.id)}</td>
                  <td className="actions-col">{items.length ? <RowMenu label={`Actions for ${u.full_name}`} items={items} /> : null}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {users === null && !error && <p className="table-empty">Loading…</p>}
        {users && !shown.length && (
          <p className="table-empty">{manager && team === "mine" && !q ? "No one in your team yet. Use Add Salesperson." : "No users match."}</p>
        )}
      </div>
      <Pagination {...peoplePage.pager} />
      {dialog?.type === "new" && <NewUser admin={admin} me={user} managers={managers} close={closeDialog} notify={notify} />}
      {dialog?.type === "upload" && <UploadUsers onClose={() => setDialog(null)} onDone={() => closeDialog({})} notify={notify} />}
      {dialog?.type === "edit" && <EditUser target={dialog.target} managers={managers} close={closeDialog} notify={notify} />}
      {dialog?.type === "reset" && <ResetPassword target={dialog.target} close={closeDialog} notify={notify} />}
      {dialog?.type === "transfer" && (
        <Transfer target={dialog.target} users={list} admin={admin} me={user} close={closeDialog} notify={notify} />
      )}
    </>
  );
}

// Activity history in tabs (Users & Access, Uploads & Downloads, Transfers, AI Assistant, Records & Emails), with
// filters and pages. Admin: everyone's (Activity Log). Manager: only their own team's (Team Activity).
function ActivityTab({ team }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("");
  const [person, setPerson] = useState("");
  const [action, setAction] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState(""); // the query, applied a moment after typing stops
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(25);
  useEffect(() => {
    const t = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(() => setPage(1), [category, person, action, from, to, search, size]);
  useEffect(() => {
    let stale = false;
    api
      .activity({ category, actor_id: person, action, date_from: from, date_to: to, q: search, page, page_size: size })
      .then((r) => !stale && (setResult(r), setError("")))
      .catch((err) => !stale && setError(err.message));
    return () => {
      stale = true;
    };
  }, [category, person, action, from, to, search, page, size]);
  const counts = result?.counts || {};
  const tabs = [{ key: "", label: "All", n: result?.all }, ...(result?.categories || []).map((c) => ({ ...c, n: counts[c.key] }))];
  const filtered = person || action || from || to || search;
  const clear = () => (setPerson(""), setAction(""), setFrom(""), setTo(""), setQuery(""));
  const rows = result?.rows || [];
  return (
    <>
      {team && (
        <p className="field-hint activity-scope">
          Activity of the Salespeople in your team (and your own). The Admin's actions are kept in the Admin's Activity Log.
        </p>
      )}
      <div className="log-tabs" role="tablist" aria-label="Activity type">
        {tabs.map((t) => (
          <button
            key={t.key || "all"}
            role="tab"
            aria-selected={category === t.key}
            className={`log-tab ${category === t.key ? "on" : ""}`}
            onClick={() => (setCategory(t.key), setAction(""))}
          >
            {t.label}
            <b>{t.n ?? "–"}</b>
          </button>
        ))}
      </div>
      <div className="people-toolbar activity-filters">
        <label className="search-field">
          <Icon name="search" size={15} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by user, action or record" aria-label="Search activity" />
        </label>
        <select value={person} onChange={(e) => setPerson(e.target.value)} aria-label="Done by">
          <option value="">Anyone</option>
          {(result?.people || []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action">
          <option value="">Any action</option>
          {(result?.actions || []).map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <label className="date-range">
          From <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} aria-label="From date" />
        </label>
        <label className="date-range">
          To <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} aria-label="To date" />
        </label>
        {filtered && (
          <button className="sf-button small" onClick={clear}>
            Clear filters
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
        <table className="sf-table users-table activity-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Done By</th>
              <th>Type</th>
              <th>Action</th>
              <th>Record</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{dateTime(r.at)}</td>
                <td>{r.by}</td>
                <td>
                  <span className={`activity-kind ${r.category}`}>
                    {(result.categories.find((c) => c.key === r.category) || {}).label}
                  </span>
                </td>
                <td>
                  <b>{r.action}</b>
                </td>
                <td>{r.target}</td>
                <td className="muted activity-details">{r.details || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {result === null && !error && <p className="table-empty">Loading…</p>}
        {result && !rows.length && <p className="table-empty">{result.all ? "No activity matches." : "No activity yet."}</p>}
      </div>
      {result && (
        <Pagination
          page={result.page}
          pages={result.pages}
          size={size}
          total={result.total}
          start={(result.page - 1) * size}
          setPage={setPage}
          setSize={setSize}
        />
      )}
    </>
  );
}

// Manage Access page: People, Permissions, Activity Log (Admin) and Team Activity (Manager)
// (#/users, #/permissions, #/activity, #/team-activity)
export default function ManageAccess({ tab = "people", user, data, reload, notify, onSelfChanged }) {
  const admin = can(user, "manage_users");
  const tabs = [
    ["people", "People", "#/users", true],
    ["permissions", "Permissions", "#/permissions", can(user, "manage_permissions")],
    ["activity", "Activity Log", "#/activity", admin],
    ["team-activity", "Team Activity", "#/team-activity", !admin && user.role === "Manager"],
  ].filter((t) => t[3]);
  const current = tabs.some((t) => t[0] === tab) ? tab : "people";
  return (
    <div className="page">
      <section className="card access-card">
        <header className="access-header">
          <h1>Manage Access</h1>
          <p>
            {admin
              ? "Add users, set their record access, and choose what each role can do."
              : "Add Salespeople to your team, set their record access, and see your team's activity."}
          </p>
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
        {current === "activity" && <ActivityTab key="all" />}
        {current === "team-activity" && <ActivityTab key="team" team />}
      </section>
    </div>
  );
}
