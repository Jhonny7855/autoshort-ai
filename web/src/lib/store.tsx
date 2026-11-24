import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, type AuthStatus } from "./api";

type Toast = { id: number; kind: "success" | "error" | "info"; message: string };
type EventPayload = Record<string, unknown> & { type: string };

type AppStore = {
  auth: AuthStatus | null;
  loading: boolean;
  /** null while unknown, false when /api is unreachable (e.g. static hosting). */
  backendOnline: boolean | null;
  refreshAuth: () => Promise<void>;
  logout: () => Promise<void>;
  toasts: Toast[];
  notify: (kind: Toast["kind"], message: string) => void;
  dismiss: (id: number) => void;
  events: EventPayload[];
  subscribe: (fn: (e: EventPayload) => void) => () => void;
  wsConnected: boolean;
};

const Ctx = createContext<AppStore | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [events, setEvents] = useState<EventPayload[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const listeners = useRef(new Set<(e: EventPayload) => void>());
  const toastSeq = useRef(0);

  const notify = useCallback((kind: Toast["kind"], message: string) => {
    const id = ++toastSeq.current;
    setToasts((prev) => [...prev.slice(-3), { id, kind, message }]);
    window.setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 5200);
  }, []);

  const dismiss = useCallback((id: number) => setToasts((prev) => prev.filter((t) => t.id !== id)), []);

  const refreshAuth = useCallback(async () => {
    try {
      const data = await api.get<AuthStatus>("/api/auth/status");
      setAuth(data);
      setBackendOnline(true);
    } catch {
      setAuth(null);
      setBackendOnline(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    setAuth(null);
    window.location.href = "/";
  }, []);

  useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

  useEffect(() => {
    if (!auth?.authenticated) return;
    let ws: WebSocket | null = null;
    let retry = 0;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const url = `${proto}://${window.location.host}/api/ws`;
      ws = new WebSocket(url);
      ws.onopen = () => {
        retry = 0;
        setWsConnected(true);
      };
      ws.onmessage = (msg) => {
        try {
          const parsed = JSON.parse(msg.data) as EventPayload;
          setEvents((prev) => [...prev.slice(-60), parsed]);
          listeners.current.forEach((fn) => fn(parsed));
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        setWsConnected(false);
        if (stopped) return;
        retry = Math.min(retry + 1, 6);
        window.setTimeout(connect, 800 * retry);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      stopped = true;
      ws?.close();
    };
  }, [auth?.authenticated]);

  const subscribe = useCallback((fn: (e: EventPayload) => void) => {
    listeners.current.add(fn);
    return () => listeners.current.delete(fn);
  }, []);

  const value = useMemo(
    () => ({ auth, loading, backendOnline, refreshAuth, logout, toasts, notify, dismiss, events, subscribe, wsConnected }),
    [auth, loading, backendOnline, refreshAuth, logout, toasts, notify, dismiss, events, subscribe, wsConnected],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppStore {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
