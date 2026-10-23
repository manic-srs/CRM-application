import React, { useEffect, useState } from "react";
import { api, setToken } from "./api";
import { EmailComposer } from "./Email";
import Header, { Sidebar } from "./Header";
import ListView from "./ListView";
import Login from "./Login";
import Modal from "./Modal";
import RecordPage from "./RecordPage";
import { AccountPage, ContactPage } from "./RelatedPages";
import SellerHome from "./SellerHome";
import TasksPage from "./TasksPage";
import UsersPage, { ChangePassword, MyProfile } from "./UsersPage";
import { Icon } from "./ui";
import { useWorkspace } from "./useWorkspace";

const SESSION_KEY = "crm-session";
const SCOPE_KEY = "crm-home-scope";

// The login (user + token) is remembered in this browser until Log Out or until the token expires.
function loadSession() {
  try {
    localStorage.removeItem("crm-user"); // older versions saved the user without a token
    const session = JSON.parse(localStorage.getItem(SESSION_KEY));
    if (session?.user && session?.token) {
      setToken(session.token);
      return session;
    }
  } catch {
    /* storage unavailable */
  }
  return null;
}
function saveSession(session) {
  setToken(session?.token);
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: stay logged in for this tab only */
  }
}

const readRoute = () => location.hash.slice(1) || "/";

export default function App() {
  const [session, setSession] = useState(loadSession);
  const [sessionExpired, setSessionExpired] = useState(false);
  const update = (next) => {
    saveSession(next);
    setSession(next);
  };
  useEffect(() => {
    // the backend said the login is no longer valid (expired, or the user was deactivated)
    const onExpired = () => {
      setSessionExpired(true);
      update(null);
    };
    addEventListener("crm-logout", onExpired);
    return () => removeEventListener("crm-logout", onExpired);
  }, []);
  useEffect(() => {
    // pick up role / name changes the Admin made since this browser logged in
    if (!session) return;
    api
      .me()
      .then((me) => {
        if (me.role !== session.user.role || me.full_name !== session.user.full_name) update({ ...session, user: me });
      })
      .catch(() => {});
  }, [session?.token]);
  if (!session)
    return (
      <Login
        sessionExpired={sessionExpired}
        onLogin={(user, token) => {
          setSessionExpired(false);
          update({ user, token });
          window.location.hash = "/";
        }}
      />
    );
  return (
    <Workspace
      key={session.user.id}
      user={session.user}
      onLogout={() => update(null)}
      onUserChanged={(user) => update({ ...session, user })}
    />
  );
}

function Workspace({ user, onLogout, onUserChanged }) {
  const [route, setRoute] = useState(readRoute);
  const [path, query = ""] = route.split("?");
  const section = path.split("/")[1] || "home";
  const id = path.split("/")[2];
  // Home: "team" (everyone's records, the default) or "mine"; remembered in this browser
  const [homeScope, setHomeScopeState] = useState(() => {
    try {
      return localStorage.getItem(SCOPE_KEY) === "mine" ? "mine" : "team";
    } catch {
      return "team";
    }
  });
  const setHomeScope = (value) => {
    setHomeScopeState(value);
    try {
      localStorage.setItem(SCOPE_KEY, value);
    } catch {
      /* ignore */
    }
  };
  const { data, run, error, loading, saving, reload, hasLoaded } = useWorkspace(section, id, user.id, homeScope);
  const [modal, setModal] = useState(null);
  const [toast, setToast] = useState("");
  const [composer, setComposer] = useState(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [emailVersion, setEmailVersion] = useState(0);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("crm-nav-collapsed") === "1";
    } catch {
      return false;
    }
  });
  const setNav = (value) => {
    setCollapsed(value);
    try {
      localStorage.setItem("crm-nav-collapsed", value ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    const onHash = () => {
      setRoute(readRoute());
      window.scrollTo(0, 0);
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 4000);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    const titles = { home: "Home", leads: "Leads", opportunities: "Opportunities", tasks: "Tasks", accounts: "Accounts", contacts: "Contacts", users: "Users" };
    document.title = `${titles[section] || "SalesTrack"} | SalesTrack`;
  }, [section]);

  const notify = (message) => setToast(message);
  const openLead = (record = null) => setModal({ type: "lead", record });
  const openTask = (relatedId = "", relatedType = relatedId ? "leads" : "general") =>
    setModal({ type: "task", relatedId, relatedType });
  const openNew = (type, defaults) => (type === "task" ? openTask() : setModal({ type, record: null, defaults }));
  const toggleTask = async (taskId) => {
    try {
      await run("completeTask", taskId);
      notify("Task marked as complete.");
    } catch (err) {
      notify(err.message);
    }
  };
  // Email composer: target = { type, field, id, name, email, firstName }
  const openEmail = (target) =>
    setComposer({
      ...target,
      greeting: `Hi ${target.firstName || ""},\n\n\n\nBest regards,\n${user.full_name}\n${user.email}`.replace("Hi ,", "Hello,"),
    });
  const convert = (leadId) => setModal({ type: "convert", record: data.leads.find((lead) => lead.id === leadId) });

  let page;
  if (section === "home") page = (
      <SellerHome
        data={data}
        user={user}
        toggleTask={toggleTask}
        openTask={openTask}
        scope={homeScope}
        setScope={setHomeScope}
      />
    );
  else if (["leads", "opportunities"].includes(section))
    page = id ? (
      <RecordPage
        key={section + id}
        collection={section}
        item={data[section].find((x) => x.id === id)}
        data={data}
        user={user}
        openLead={openLead}
        openTask={openTask}
        toggleTask={toggleTask}
        convert={convert}
        setModal={setModal}
        openEmail={openEmail}
        emailVersion={emailVersion}
      />
    ) : (
      <ListView key={route} collection={section} data={data} user={user} openNew={openNew} setModal={setModal} query={query} />
    );
  else if (section === "accounts")
    page = id ? (
      <AccountPage id={id} data={data} openNew={openNew} openEmail={openEmail} emailVersion={emailVersion} />
    ) : (
      <ListView key={route} collection="accounts" data={data} user={user} openNew={openNew} setModal={setModal} query={query} />
    );
  else if (section === "contacts")
    page = id ? (
      <ContactPage id={id} data={data} openTask={openTask} openEmail={openEmail} emailVersion={emailVersion} />
    ) : (
      <ListView key={route} collection="contacts" data={data} user={user} openNew={openNew} setModal={setModal} query={query} />
    );
  else if (section === "users" && user.role === "Admin") page = <UsersPage user={user} data={data} reload={reload} notify={notify} onSelfChanged={onUserChanged} />;
  else if (section === "tasks")
    page = <TasksPage key={route} data={data} user={user} toggleTask={toggleTask} openTask={openTask} setModal={setModal} query={query} />;
  else
    page = (
      <div className="page">
        <section className="card pad">
          <h2>Page not found</h2>
          <a href="#/">Back to Home</a>
        </section>
      </div>
    );

  return (
    <div className={`app ${collapsed ? "nav-collapsed" : ""}`}>
      <Header
        section={section}
        user={user}
        data={data}
        onLogout={onLogout}
        openNew={openNew}
        run={run}
        notify={notify}
        reload={reload}
        openPassword={() => setPasswordOpen(true)}
        openProfile={() => setProfileOpen(true)}
        toggleSidebar={() => setNav(!collapsed)}
      />
      <Sidebar section={section} data={data} user={user} collapsed={collapsed} />
      <main className="app-main">
        {error && (
          <div className="alert" role="alert">
            <Icon name="warn" size={16} />
            <span>{error}</span>
            <button className="sf-button small" onClick={() => reload().catch(() => {})}>
              Reload data
            </button>
          </div>
        )}
        {loading && !hasLoaded ? (
          <div className="spinner-wrap" role="status">
            <span className="spinner" />
            Loading…
          </div>
        ) : !hasLoaded ? (
          <div className="page">
            <section className="card pad">
              <h2>Can't reach the server</h2>
              <p>Start the backend, then select Reload data.</p>
            </section>
          </div>
        ) : (
          page
        )}
      </main>
      {saving && (
        <div className="saving" role="status">
          Saving…
        </div>
      )}
      {passwordOpen && <ChangePassword close={() => setPasswordOpen(false)} notify={notify} />}
      {profileOpen && (
        <MyProfile
          user={user}
          close={() => setProfileOpen(false)}
          notify={notify}
          onSaved={(updated) => {
            onUserChanged(updated);
            reload().catch(() => {});
          }}
        />
      )}
      {modal && <Modal modal={modal} close={() => setModal(null)} data={data} run={run} notify={notify} user={user} />}
      {composer && (
        <EmailComposer
          target={composer}
          user={user}
          onClose={() => setComposer(null)}
          onSent={(email) => {
            setComposer(null);
            setEmailVersion((v) => v + 1);
            notify(
              email.status === "Sent"
                ? `Email "${email.subject}" was sent to ${email.to_address}.`
                : ["Gmail", "Outlook"].includes(email.status)
                  ? `Email saved on the record. Finish sending it in ${email.status}.`
                  : `Email saved but not sent: ${email.error}`,
            );
          }}
        />
      )}
      {toast && (
        <div className="toast" role="status">
          <Icon name="check" size={16} />
          <span>{toast}</span>
          <button aria-label="Close" onClick={() => setToast("")}>
            <Icon name="close" size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
