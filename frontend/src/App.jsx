import React, { useEffect, useState } from "react";
import { EmailComposer } from "./Email";
import Header, { Sidebar } from "./Header";
import ListView from "./ListView";
import Login from "./Login";
import Modal from "./Modal";
import RecordPage from "./RecordPage";
import { AccountPage, ContactPage } from "./RelatedPages";
import SellerHome from "./SellerHome";
import TasksPage from "./TasksPage";
import { Icon } from "./ui";
import { useWorkspace } from "./useWorkspace";

const USER_KEY = "crm-user";

// The logged-in user is remembered in this browser only (no tokens yet in this POC).
function loadUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY)) || null;
  } catch {
    return null;
  }
}
function saveUser(user) {
  try {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(USER_KEY);
  } catch {
    /* storage unavailable: stay logged in for this tab only */
  }
}

const readRoute = () => location.hash.slice(1) || "/";

export default function App() {
  const [user, setUser] = useState(loadUser);
  if (!user)
    return (
      <Login
        onLogin={(u) => {
          saveUser(u);
          setUser(u);
          window.location.hash = "/";
        }}
      />
    );
  return (
    <Workspace
      user={user}
      onLogout={() => {
        saveUser(null);
        setUser(null);
      }}
    />
  );
}

function Workspace({ user, onLogout }) {
  const [route, setRoute] = useState(readRoute);
  const [path, query = ""] = route.split("?");
  const section = path.split("/")[1] || "home";
  const id = path.split("/")[2];
  const { data, run, error, loading, saving, reload, hasLoaded } = useWorkspace(section, id, user.id);
  const [modal, setModal] = useState(null);
  const [toast, setToast] = useState("");
  const [composer, setComposer] = useState(null);
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
    const titles = { home: "Home", leads: "Leads", opportunities: "Opportunities", tasks: "Tasks", accounts: "Accounts", contacts: "Contacts" };
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
  if (section === "home") page = <SellerHome data={data} user={user} toggleTask={toggleTask} openTask={openTask} />;
  else if (["leads", "opportunities"].includes(section))
    page = id ? (
      <RecordPage
        key={section + id}
        collection={section}
        item={data[section].find((x) => x.id === id)}
        data={data}
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
