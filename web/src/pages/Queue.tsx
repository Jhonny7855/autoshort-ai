import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api, type QueueItem } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, Empty, PageHeader, relTime, SectionTitle, Spinner, StatusChip } from "../components/ui";
import { Icon } from "../components/icons";

type Column = { key: string; label: string; statuses: string[]; accent: string };

const COLUMNS: Column[] = [
  { key: "IDEATION", label: "Ideation", statuses: ["IDEA", "RESEARCHING", "SCRIPT_READY"], accent: "bg-slate-400" },
  { key: "REVIEW", label: "Review", statuses: ["WAITING_FOR_APPROVAL"], accent: "bg-amber-400" },
  {
    key: "PRODUCTION",
    label: "Production",
    statuses: ["GENERATING_AUDIO", "GENERATING_VISUALS", "RENDERING", "QUALITY_CHECK"],
    accent: "bg-violet-400",
  },
  { key: "READY", label: "Ready", statuses: ["READY_TO_UPLOAD", "UPLOADING"], accent: "bg-emerald-400" },
  { key: "DONE", label: "Published", statuses: ["SCHEDULED", "PUBLISHED"], accent: "bg-green-400" },
  { key: "ISSUES", label: "Issues", statuses: ["FAILED", "CANCELLED"], accent: "bg-rose-400" },
];

export default function Queue() {
  const { notify, subscribe } = useApp();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);

  async function load() {
    try {
      const data = await api.get<{ items: QueueItem[]; counts: Record<string, number> }>("/api/queue");
      setItems(data.items);
      setCounts(data.counts);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load queue");
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(load, 20000);
    const unsub = subscribe((e) => {
      if (["queue_update", "pipeline", "pipeline_done", "upload_done", "automation_status"].includes(e.type)) void load();
    });
    return () => {
      window.clearInterval(id);
      unsub();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function action(id: number, kind: "retry" | "approve" | "cancel" | "prioritize") {
    setBusy(`${kind}-${id}`);
    try {
      if (kind === "retry") await api.post(`/api/queue/${id}/retry`);
      else if (kind === "approve") await api.post(`/api/queue/${id}/approve`);
      else if (kind === "cancel") await api.del(`/api/queue/${id}`);
      else await api.post(`/api/queue/${id}/status`, { priority: 10 });
      notify("success", `${kind} complete`);
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : `${kind} failed`);
    } finally {
      setBusy(null);
    }
  }

  async function drop(target: QueueItem) {
    if (dragId === null || dragId === target.id) {
      setDragId(null);
      setOverCol(null);
      return;
    }
    try {
      await api.post("/api/queue/reorder", { queue_id: dragId, position: target.position });
      setDragId(null);
      setOverCol(null);
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Reorder failed");
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Studio"
        title="Queue"
        subtitle="Every stage of the pipeline. Drag a card onto another to reorder."
        actions={
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(counts)
              .filter(([, v]) => v > 0)
              .slice(0, 6)
              .map(([k, v]) => (
                <span key={k} className="chip border-white/10 bg-white/[0.04] text-slate-400">
                  <span className="capitalize">{k.replaceAll("_", " ").toLowerCase()}</span>
                  <span className="numeric text-slate-500">{v}</span>
                </span>
              ))}
          </div>
        }
      />

      {items.length === 0 ? (
        <Empty
          title="Queue is empty"
          body="Start automation or generate an idea to fill the pipeline."
          icon="layers"
          action={
            <Link to="/ideas" className="btn-primary btn-sm">
              <Icon name="bulb" className="h-3.5 w-3.5" />
              Generate an idea
            </Link>
          }
        />
      ) : (
        <div className="scrollbar-thin mask-fade-x -mx-1 flex gap-3 overflow-x-auto px-1 pb-3">
          {COLUMNS.map((col) => {
            const colItems = items.filter((i) => col.statuses.includes(i.status));
            const isOver = overCol === col.key && dragId !== null;
            return (
              <div
                key={col.key}
                onDragOver={(e) => {
                  e.preventDefault();
                  setOverCol(col.key);
                }}
                onDragLeave={() => setOverCol((prev) => (prev === col.key ? null : prev))}
                className={cx(
                  "w-[292px] shrink-0 rounded-2xl border p-2 transition-colors duration-200",
                  isOver ? "border-violet-500/40 bg-violet-500/[0.06]" : "border-transparent",
                )}
              >
                <div className="mb-2 flex items-center gap-2 px-1">
                  <span className={cx("h-1.5 w-1.5 rounded-full", col.accent)} />
                  <span className="text-2xs font-bold uppercase tracking-[0.14em] text-slate-400">{col.label}</span>
                  <span className="numeric ml-auto rounded-md bg-white/[0.05] px-1.5 py-0.5 text-[10px] text-slate-400">
                    {colItems.length}
                  </span>
                </div>

                <div className="space-y-2">
                  <AnimatePresence initial={false} mode="popLayout">
                    {colItems.map((item) => (
                      <motion.div
                        key={item.id}
                        layout
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: dragId === item.id ? 0.4 : 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.96 }}
                        transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
                        draggable
                        onDragStart={() => setDragId(item.id)}
                        onDragEnd={() => {
                          setDragId(null);
                          setOverCol(null);
                        }}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={() => drop(item)}
                        className="card cursor-grab p-3 transition-colors hover:border-white/[0.14] active:cursor-grabbing"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="line-clamp-2 text-[11.5px] font-semibold leading-snug text-slate-200">{item.topic}</div>
                          {item.priority > 0 && (
                            <span className="chip shrink-0 border-amber-500/25 bg-amber-500/10 text-[9px] text-amber-300">
                              P{item.priority}
                            </span>
                          )}
                        </div>

                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          <StatusChip status={item.status} />
                          {item.quality_score !== null && (
                            <span
                              className={cx(
                                "chip",
                                item.quality_score >= 75
                                  ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                                  : "border-amber-500/25 bg-amber-500/10 text-amber-300",
                              )}
                            >
                              Q{Math.round(item.quality_score)}
                            </span>
                          )}
                        </div>

                        {item.last_error && (
                          <div className="mt-2 line-clamp-2 rounded-md bg-rose-500/[0.07] px-1.5 py-1 text-[10px] leading-relaxed text-rose-300">
                            {item.last_error}
                          </div>
                        )}

                        <div className="mt-2 flex items-center justify-between text-[10px] text-slate-600">
                          <span>{relTime(item.updated_at)}</span>
                          <button
                            onClick={() => setExpanded(expanded === item.id ? null : item.id)}
                            className="flex items-center gap-0.5 transition hover:text-slate-300"
                          >
                            {expanded === item.id ? "hide" : "details"}
                            <Icon
                              name="chevron"
                              className={cx("h-2.5 w-2.5 transition-transform", expanded === item.id && "rotate-90")}
                              strokeWidth={2.6}
                            />
                          </button>
                        </div>

                        <AnimatePresence initial={false}>
                          {expanded === item.id && (
                            <motion.div
                              initial={{ opacity: 0, height: 0 }}
                              animate={{ opacity: 1, height: "auto" }}
                              exit={{ opacity: 0, height: 0 }}
                              transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
                              className="overflow-hidden"
                            >
                              <div className="mt-2 space-y-1.5 border-t border-white/[0.06] pt-2">
                                {item.timeline.map((t, i) => (
                                  <div key={i} className="flex items-start gap-1.5 text-[10px]">
                                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-violet-400" />
                                    <span className="capitalize text-slate-400">{t.status.replaceAll("_", " ").toLowerCase()}</span>
                                    <span className="ml-auto shrink-0 text-slate-600">{relTime(t.at)}</span>
                                  </div>
                                ))}
                                {item.timeline.length === 0 && <div className="text-[10px] text-slate-600">No timeline entries.</div>}
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>

                        <div className="mt-2.5 flex flex-wrap gap-1">
                          {["WAITING_FOR_APPROVAL", "READY_TO_UPLOAD"].includes(item.status) && (
                            <button onClick={() => action(item.id, "approve")} disabled={busy !== null} className="btn-ghost btn-sm">
                              {busy === `approve-${item.id}` ? <Spinner /> : "Approve"}
                            </button>
                          )}
                          {item.status === "FAILED" && (
                            <button onClick={() => action(item.id, "retry")} disabled={busy !== null} className="btn-primary btn-sm">
                              {busy === `retry-${item.id}` ? <Spinner /> : "Retry"}
                            </button>
                          )}
                          <button onClick={() => action(item.id, "prioritize")} disabled={busy !== null} className="btn-ghost btn-sm">
                            Prioritize
                          </button>
                          <Link to={`/video?idea=${item.idea_id}`} className="btn-ghost btn-sm">
                            Open
                          </Link>
                          <button onClick={() => action(item.id, "cancel")} disabled={busy !== null} className="btn-danger btn-sm">
                            Cancel
                          </button>
                        </div>
                      </motion.div>
                    ))}
                  </AnimatePresence>

                  {colItems.length === 0 && (
                    <div className="rounded-xl border border-dashed border-white/[0.06] px-3 py-6 text-center text-[10px] text-slate-600">
                      empty
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Card>
        <SectionTitle title="Retry policy" subtitle="Automatic retries with attempt tracking" />
        <p className="text-[11.5px] leading-relaxed text-slate-400">
          Failed items are retried automatically up to three attempts by the engine. Errors are written to the item
          timeline and the Logs page. Uploads are never duplicated: the YouTube video id is unique per channel.
        </p>
      </Card>
    </div>
  );
}
