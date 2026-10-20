import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiRequest, normalizeWorkspace } from "./api";

const empty = {
  leads: [],
  opportunities: [],
  tasks: [],
  users: [],
  accounts: [],
  contacts: [],
  home: null,
  notifications: [],
};
// userId = the logged-in user: Home cards and the bell show "owned by me".
export function useWorkspace(collection, id, userId) {
  const [data, setData] = useState(empty);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [hasLoaded, setHasLoaded] = useState(false);
  const notificationOwner = userId ? String(userId) : "";
  const sequence = useRef(0),
    busy = useRef(false);
  const reload = useCallback(async () => {
    const ticket = ++sequence.current;
    setLoading(true);
    try {
      const names = [
        "leads",
        "opportunities",
        "tasks",
        "users",
        "accounts",
        "contacts",
        "home",
      ];
      const path = (name) =>
        name === "home" && notificationOwner
          ? `/home?owner_id=${notificationOwner}`
          : `/${name}`;
      const [responses, detail, notifications] = await Promise.all([
        Promise.all(names.map((name) => apiRequest(path(name)))),
        id && ["leads", "opportunities"].includes(collection)
          ? apiRequest(`/${collection}/${id}`)
          : null,
        notificationOwner
          ? apiRequest(`/notifications?user_id=${notificationOwner}`)
          : [],
      ]);
      if (ticket !== sequence.current) return;
      const raw = Object.fromEntries(
        names.map((name, index) => [name, responses[index]]),
      );
      setData(
        normalizeWorkspace(
          { ...raw, notifications },
          detail ? { collection, record: detail } : null,
        ),
      );
      setError("");
      setHasLoaded(true);
    } catch (err) {
      if (ticket === sequence.current) setError(err.message);
      throw err;
    } finally {
      if (ticket === sequence.current) setLoading(false);
    }
  }, [collection, id, notificationOwner]);
  useEffect(() => {
    reload().catch(() => {});
    return () => {
      sequence.current++;
    };
  }, [reload]);
  const latestReload = useRef(reload);
  latestReload.current = reload;
  const run = useCallback(
    async (name, ...args) => {
      if (busy.current)
        throw new Error(
          "A change is already being saved. Please try again in a moment.",
        );
      busy.current = true;
      setSaving(true);
      try {
        const result = await api[name](...args);
        try {
          await latestReload.current();
        } catch {
          setError(
            "Your change was saved, but the page could not refresh. Reload the latest data before continuing.",
          );
        }
        return result;
      } catch (err) {
        setError(err.message);
        throw err;
      } finally {
        busy.current = false;
        setSaving(false);
      }
    },
    [],
  );
  return {
    data,
    run,
    reload,
    loading,
    saving,
    error,
    hasLoaded,
    notificationOwner,
  };
}
