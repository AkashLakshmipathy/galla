import { useCallback, useEffect, useRef, useState } from "react";

/** Poll an async loader on an interval, pausing while the tab is hidden.
 *
 *  The trace strip is the reason this exists: agents finish out of band, so the
 *  screen has to discover that on its own. Firestore's `onSnapshot` would push
 *  instead of pull, but it needs client credentials in the bundle; polling the
 *  API keeps the app credential-free and behaves identically on camera.
 */
export function usePolling(loader, { interval = 1500, active = true, deps = [] } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const saved = useRef(loader);
  saved.current = loader;

  const refresh = useCallback(async () => {
    try {
      const next = await saved.current();
      setData(next);
      setError(null);
      return next;
    } catch (err) {
      setError(err);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer;
    const tick = async () => {
      if (cancelled) return;
      if (!document.hidden) await refresh();
      if (!cancelled && active && interval) timer = setTimeout(tick, interval);
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, interval, active, ...deps]);

  return { data, error, loading, refresh, setData };
}

export function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

/** Toast queue — one message at a time, auto-dismissed at ~3.2s per the tokens. */
export function useToast() {
  const [toast, setToast] = useState(null);
  const timer = useRef();
  const show = useCallback((message) => {
    clearTimeout(timer.current);
    setToast(message);
    timer.current = setTimeout(() => setToast(null), 3200);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);
  return [toast, show];
}
