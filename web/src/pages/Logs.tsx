import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, Empty, PageHeader, Spinner, Tabs } from "../components/ui";
import { Icon } from "../components/icons";

type LogRow = {
  id: number;
  user_id: number | null;
  level: string;
  scope: string | null;
  message: string;
  context: string | null;
  created_at: string;
};

const LEVELS = ["all", "info", "warn", "error"] as const;

const LEVEL_TONE: Record<string, string> = {
  info: "border-sky-500/25 bg-sky-500/10 text-sky-300",
  warn: "border-amber-500/25 bg-amber-500/10 text-amber-300",
  error: "border-rose-500/25 bg-rose-500/10 text-rose-300",
};

export default function LogsPage() {
  const { notify, subscribe } = useApp();
  const [logs, setLogs] = useState<LogRow[]>([]);
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  async function load() {
    try {
      const path = level === "all" ? "/api/system/logs?limit=300" : `/api/system/logs?limit=300&level=${level}`;
      const res = await api.get<{ logs: LogRow[] }>(path);
      setLogs(res.logs);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load logs");
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(load, 12000);
    const unsub = subscribe((e) => {
      if (["pipeline", "pipeline_error", "upload_done", "automation_status"].includes(e.type)) void load();
    });
    return () => {
      window.clearInterval(id);
      unsub();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [level]);

  async function clearAll() {
    if (!window.confirm("Delete all log entries for this account?")) return;
    setBusy(true);
    try {
      await api.del("/api/system/logs");
      notify("success", "Logs cleared");
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Clear failed");
    } finally {
      setBusy(false);
    }
  }

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return logs;
    return logs.filter(
      (row) =>
        row.message.toLowerCase().includes(needle) ||
        (row.scope ?? "").toLowerCase().includes(needle) ||
        (row.context ?? "").toLowerCase().includes(needle),
    );
  }, [logs, query]);

  const counts = useMemo(() => {
    const out: Record<string, number> = { info: 0, warn: 0, error: 0 };
    logs.forEach((row) => {
      out[row.level] = (out[row.level] ?? 0) + 1;
    });
    return out;
  }, [logs]);

  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="Configuration"
        title="Logs"
        subtitle="Real events written by the backend. Nothing is simulated."
        actions={
          <button onClick={clearAll} disabled={busy || logs.length === 0} className="btn-danger btn-sm">
            {busy ? <Spinner /> : <Icon name="trash" className="h-3.5 w-3.5" />}
            Clear logs
          </button>
        }
      />

      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-3">
          <Tabs
            tabs={LEVELS.map((option) => ({
              key: option,
              label: option === "all" ? "All" : option,
              count: option === "all" ? logs.length : counts[option],
            }))}
            value={level}
            onChange={(k) => setLevel(k as (typeof LEVELS)[number])}
          />
          <div className="relative ml-auto w-full max-w-xs">
            <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <input
              className="input py-2 pl-9 text-xs"
              placeholder="Filter by message, scope or context…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>
      </Card>

      {filtered.length === 0 ? (
        <Empty
          title={logs.length === 0 ? "No log entries yet" : "No matches"}
          body={
            logs.length === 0
              ? "Run automation or a pipeline step and events will appear here."
              : "Adjust the level filter or search term."
          }
          icon="list"
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="divide-y divide-white/[0.05]">
            {filtered.map((row, i) => (
              <motion.div
                key={row.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2, delay: Math.min(i * 0.007, 0.2) }}
                className="px-4 py-2.5 transition-colors hover:bg-white/[0.025]"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={cx(
                      "chip border text-[9px] uppercase",
                      LEVEL_TONE[row.level] ?? "border-white/10 bg-white/5 text-slate-400",
                    )}
                  >
                    {row.level}
                  </span>
                  {row.scope && <span className="font-mono text-[10px] text-slate-500">{row.scope}</span>}
                  <span className="min-w-0 flex-1 text-[11.5px] text-slate-200">{row.message}</span>
                  <span className="shrink-0 font-mono text-2xs text-slate-600">
                    {new Date(row.created_at).toLocaleTimeString()}
                  </span>
                </div>
                {row.context && (
                  <div className="mt-1.5">
                    <button
                      onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                      className="flex items-center gap-1 text-2xs text-slate-500 transition hover:text-slate-300"
                    >
                      <Icon
                        name="chevron"
                        className={cx("h-2.5 w-2.5 transition-transform", expanded === row.id && "rotate-90")}
                        strokeWidth={2.6}
                      />
                      context
                    </button>
                    <AnimatePresence initial={false}>
                      {expanded === row.id && (
                        <motion.pre
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          className="mt-1 overflow-auto rounded-lg border border-white/[0.05] bg-black/40 p-2 font-mono text-[10px] leading-relaxed text-slate-400"
                          style={{ maxHeight: 192 }}
                        >
                          {(() => {
                            try {
                              return JSON.stringify(JSON.parse(row.context), null, 2);
                            } catch {
                              return row.context;
                            }
                          })()}
                        </motion.pre>
                      )}
                    </AnimatePresence>
                  </div>
                )}
              </motion.div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
