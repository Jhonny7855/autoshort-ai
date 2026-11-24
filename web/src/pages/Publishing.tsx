import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import {
  Card,
  cx,
  Empty,
  PageHeader,
  relTime,
  Reveal,
  SectionTitle,
  Spinner,
  StatusChip,
  Tabs,
} from "../components/ui";
import { Icon } from "../components/icons";

type PubItem = {
  id: number;
  queue_id: number | null;
  project_id: number;
  title: string | null;
  description: string | null;
  hashtags: string[];
  status: string;
  youtube_url: string | null;
  youtube_video_id: string | null;
  scheduled_at: string | null;
  published_at: string | null;
  notes: string | null;
  download_url: string | null;
  thumbnail_url: string | null;
  package_ready: boolean;
  updated_at: string;
};

type Payload = {
  records: PubItem[];
  groups: Record<string, PubItem[]>;
  counts: Record<string, number>;
};

type Summary = {
  enabled: boolean;
  at: string;
  per_day: number;
  next_run_at: string | null;
  counts: Record<string, number>;
  youtube_configured: boolean;
};

const TABS = [
  { key: "ready", label: "Ready" },
  { key: "pending_review", label: "Review" },
  { key: "scheduled", label: "Scheduled" },
  { key: "published", label: "Published" },
  { key: "failed", label: "Failed" },
];

const EMPTY_COPY: Record<string, { title: string; body: string }> = {
  ready: {
    title: "No Shorts waiting to publish",
    body: "Generate a video and it lands here with a download link and copy-ready metadata.",
  },
  pending_review: {
    title: "Nothing awaiting review",
    body: "Videos held back by the quality gate appear here for you to approve or reject.",
  },
  scheduled: { title: "No scheduled Shorts", body: "Assign a date and time to line up your publishing slots." },
  published: { title: "Nothing published yet", body: "Paste the YouTube URL of a Short you uploaded to mark it published." },
  failed: { title: "No failures", body: "Anything that failed to package or confirm shows up here." },
};

function CopyButton({ text, label }: { text: string; label: string }) {
  const { notify } = useApp();
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!text) {
      notify("info", `${label} is empty`);
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement("textarea");
      el.value = text;
      el.style.position = "fixed";
      el.style.opacity = "0";
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
    notify("success", `${label} copied`);
  }

  return (
    <button onClick={copy} className={cx("btn-ghost btn-sm", copied && "border-emerald-500/35 text-emerald-300")} title={`Copy ${label.toLowerCase()}`}>
      <Icon name={copied ? "check" : "copy"} className="h-3 w-3" strokeWidth={2} />
      {label}
    </button>
  );
}

export default function Publishing() {
  const { notify } = useApp();
  const [data, setData] = useState<Payload | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tab, setTab] = useState("ready");
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [urlDraft, setUrlDraft] = useState<Record<number, string>>({});
  const [open, setOpen] = useState<number | null>(null);
  const [editing, setEditing] = useState<Record<number, { title: string; description: string; hashtags: string }>>({});

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([api.get<Payload>("/api/publish"), api.get<Summary>("/api/publish/summary")]);
      setData(p);
      setSummary(s);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load publishing queue");
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(kind: string, rec: PubItem) {
    setBusy(`${kind}-${rec.id}`);
    try {
      if (kind === "confirm") {
        const url = (urlDraft[rec.id] ?? "").trim();
        if (!url) {
          notify("error", "Paste the YouTube URL before confirming");
          setBusy(null);
          return;
        }
        await api.post(`/api/publish/${rec.id}/confirm`, { youtube_url: url });
        notify("success", "Marked as published with your URL");
      } else if (kind === "approve") {
        await api.post(`/api/publish/${rec.id}/approve`);
        notify("success", "Approved — moved to ready");
      } else if (kind === "reject") {
        await api.post(`/api/publish/${rec.id}/reject`, { note: "Rejected from publishing dashboard" });
        notify("info", "Rejected");
      } else if (kind === "schedule") {
        const at = window.prompt("Schedule for (ISO or YYYY-MM-DD HH:MM):", rec.scheduled_at ?? "");
        if (at === null) {
          setBusy(null);
          return;
        }
        await api.post(`/api/publish/${rec.id}/schedule`, { scheduled_at: at.trim() || null });
        notify("success", at.trim() ? "Scheduled" : "Schedule cleared");
      } else if (kind === "save") {
        const draft = editing[rec.id];
        if (draft) {
          await api.patch(`/api/publish/${rec.id}`, {
            title: draft.title,
            description: draft.description,
            hashtags: draft.hashtags.split(/[\s,]+/).filter(Boolean),
          });
          notify("success", "Metadata saved");
        }
      } else if (kind === "generate") {
        const res = await api.post<{ results: { status: string }[] }>("/api/automation/daily/run?count=1");
        const status = res.results?.[0]?.status ?? "nothing to do";
        notify("success", `Generation finished: ${status}`);
      }
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : `${kind} failed`);
    } finally {
      setBusy(null);
    }
  }

  async function toggleDaily() {
    if (!summary) return;
    setBusy("daily");
    try {
      await api.post("/api/automation/daily", { enabled: !summary.enabled });
      await load();
      notify("success", summary.enabled ? "Daily generation paused" : "Daily generation enabled");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Could not update the daily schedule");
    } finally {
      setBusy(null);
    }
  }

  const rows = data?.groups?.[tab] ?? [];
  const tabs = useMemo(() => TABS.map((t) => ({ ...t, count: data?.counts?.[t.key] ?? 0 })), [data]);
  const empty = EMPTY_COPY[tab] ?? { title: "Nothing here yet", body: "No videos in this state." };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Publish"
        title="Publishing"
        subtitle="Finished Shorts are packaged on this machine. Nothing is marked published until you paste the real URL."
        actions={
          <>
            <button onClick={() => act("generate", {} as PubItem)} disabled={busy !== null} className="btn-ghost">
              {busy?.startsWith("generate") ? <Spinner /> : <Icon name="sparkles" className="h-4 w-4" />}
              Generate now
            </button>
            <a href="https://studio.youtube.com" target="_blank" rel="noreferrer" className="btn-primary">
              <Icon name="external" className="h-4 w-4" strokeWidth={1.9} />
              Open YouTube Studio
            </a>
          </>
        }
      />

      <Reveal>
        <div className="card-lit p-5">
          <div className="relative grid gap-5 md:grid-cols-[1fr_auto]">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[15px] font-semibold text-white">Daily generation</h2>
                <span
                  className={cx(
                    "chip",
                    summary?.enabled ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" : "border-white/10 bg-white/5 text-slate-400",
                  )}
                >
                  <span className={cx("h-1.5 w-1.5 rounded-full", summary?.enabled ? "animate-breathe bg-emerald-400" : "bg-slate-500")} />
                  {summary ? (summary.enabled ? "On" : "Off") : "loading"}
                </span>
              </div>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-slate-400">
                {summary
                  ? `${summary.per_day} Short${summary.per_day === 1 ? "" : "s"} per day at ${summary.at} · next run ${relTime(summary.next_run_at)}`
                  : "Loading schedule"}
              </p>

              <div className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-5">
                {TABS.map((t) => (
                  <div
                    key={t.key}
                    className="rounded-lg border border-white/[0.05] bg-white/[0.025] px-2.5 py-2 transition-colors hover:border-white/10"
                  >
                    <div className="truncate text-2xs uppercase tracking-wider text-slate-600">{t.label}</div>
                    <div className="numeric mt-0.5 text-[15px] font-bold text-slate-200">{summary?.counts?.[t.key] ?? 0}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-col justify-between gap-3 md:w-[190px]">
              <div className="rounded-xl border border-white/[0.06] bg-ink-950/40 p-3">
                <div className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-slate-600">
                  <Icon name="shield" className="h-3 w-3" />
                  Publishing mode
                </div>
                <div className="mt-1 text-[12px] font-semibold text-slate-200">
                  {summary?.youtube_configured ? "API + manual" : "Manual only"}
                </div>
                <div className="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">
                  {summary?.youtube_configured ? "YouTube credentials connected" : "No Google credentials configured"}
                </div>
              </div>
              <button onClick={toggleDaily} disabled={busy !== null || !summary} className={cx(summary?.enabled ? "btn-ghost" : "btn-primary", "btn-sm")}>
                {busy === "daily" ? <Spinner /> : <Icon name={summary?.enabled ? "pause" : "play"} className="h-3.5 w-3.5" strokeWidth={2} />}
                {summary?.enabled ? "Pause daily" : "Enable daily"}
              </button>
            </div>
          </div>
        </div>
      </Reveal>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs tabs={tabs} value={tab} onChange={setTab} />
        <span className="text-2xs text-slate-600">
          {rows.length} item{rows.length === 1 ? "" : "s"} in this view
        </span>
      </div>

      {loading ? (
        <div className="grid place-items-center py-16">
          <Spinner className="h-7 w-7" />
        </div>
      ) : rows.length === 0 ? (
        <Empty title={empty.title} body={empty.body} icon="upload" />
      ) : (
        <div className="space-y-3">
          <AnimatePresence initial={false} mode="popLayout">
            {rows.map((rec, index) => {
              const expanded = open === rec.id;
              const draft =
                editing[rec.id] ?? {
                  title: rec.title ?? "",
                  description: rec.description ?? "",
                  hashtags: (rec.hashtags ?? []).join(" "),
                };
              const hashtagLine = (rec.hashtags ?? []).join(" ");
              return (
                <motion.div
                  key={rec.id}
                  layout
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.98 }}
                  transition={{ duration: 0.3, delay: Math.min(index * 0.03, 0.15), ease: [0.16, 1, 0.3, 1] }}
                >
                  <Card className="group p-0 transition-colors duration-300 hover:border-white/[0.12]">
                    <div className="flex flex-col gap-4 p-4 sm:flex-row">
                      <div className="w-full shrink-0 sm:w-[112px]">
                        <div className="relative aspect-[9/16] overflow-hidden rounded-lg bg-ink-800 ring-1 ring-white/[0.06]">
                          {rec.thumbnail_url ? (
                            <img
                              src={rec.thumbnail_url}
                              alt=""
                              className="h-full w-full object-cover transition-transform duration-500 ease-smooth group-hover:scale-[1.03]"
                            />
                          ) : (
                            <div className="grid h-full place-items-center text-[10px] text-slate-600">no preview</div>
                          )}
                          {rec.package_ready && (
                            <span className="absolute left-1.5 top-1.5 rounded-md bg-black/70 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-300 backdrop-blur">
                              packaged
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-[13.5px] font-semibold text-slate-100">{rec.title || "Untitled"}</div>
                            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-slate-500">
                              <span>Updated {relTime(rec.updated_at)}</span>
                              {rec.scheduled_at && <span>· scheduled {relTime(rec.scheduled_at)}</span>}
                              {rec.published_at && <span>· published {relTime(rec.published_at)}</span>}
                            </div>
                          </div>
                          <StatusChip status={rec.status} />
                        </div>

                        {rec.notes && (
                          <div className="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-300/85">
                            <Icon name="alert" className="mt-0.5 h-3 w-3 shrink-0" />
                            {rec.notes}
                          </div>
                        )}

                        {rec.youtube_url && (
                          <a
                            href={rec.youtube_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-2 inline-flex max-w-full items-center gap-1.5 truncate text-[11px] text-cyan-300 transition hover:text-cyan-200"
                          >
                            <Icon name="external" className="h-3 w-3 shrink-0" />
                            <span className="truncate">{rec.youtube_url}</span>
                          </a>
                        )}

                        <div className="mt-3 flex flex-wrap items-center gap-1.5">
                          {rec.download_url && (
                            <a href={rec.download_url} className="btn-primary btn-sm" download>
                              <Icon name="download" className="h-3 w-3" strokeWidth={2.2} />
                              Download MP4
                            </a>
                          )}
                          <CopyButton text={rec.title ?? ""} label="Title" />
                          <CopyButton text={rec.description ?? ""} label="Description" />
                          <CopyButton text={hashtagLine} label="Hashtags" />
                          <button onClick={() => setOpen(expanded ? null : rec.id)} className="btn-ghost btn-sm">
                            <Icon name="doc" className="h-3 w-3" />
                            {expanded ? "Hide metadata" : "Edit metadata"}
                          </button>
                          {rec.status === "pending_review" && (
                            <>
                              <button onClick={() => act("approve", rec)} disabled={busy !== null} className="btn-primary btn-sm">
                                {busy === `approve-${rec.id}` ? <Spinner /> : "Approve"}
                              </button>
                              <button onClick={() => act("reject", rec)} disabled={busy !== null} className="btn-danger btn-sm">
                                Reject
                              </button>
                            </>
                          )}
                          {rec.status !== "published" && (
                            <button onClick={() => act("schedule", rec)} disabled={busy !== null} className="btn-ghost btn-sm">
                              <Icon name="calendar" className="h-3 w-3" />
                              {rec.scheduled_at ? "Reschedule" : "Schedule"}
                            </button>
                          )}
                        </div>

                        {rec.status !== "published" && (
                          <div className="mt-3 rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5">
                            <div className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                              <Icon name="check" className="h-3 w-3" strokeWidth={2.4} />
                              Confirm publication
                            </div>
                            <div className="mt-1.5 flex flex-wrap gap-1.5">
                              <input
                                value={urlDraft[rec.id] ?? ""}
                                onChange={(e) => setUrlDraft((prev) => ({ ...prev, [rec.id]: e.target.value }))}
                                placeholder="https://youtube.com/shorts/..."
                                className="input min-w-0 flex-1 text-xs"
                              />
                              <button onClick={() => act("confirm", rec)} disabled={busy !== null} className="btn-primary btn-sm">
                                {busy === `confirm-${rec.id}` ? <Spinner /> : "Mark published"}
                              </button>
                            </div>
                            <div className="mt-1 text-[10px] text-slate-600">
                              Upload the MP4 in YouTube Studio, then paste the resulting URL here.
                            </div>
                          </div>
                        )}

                        <AnimatePresence initial={false}>
                          {expanded && (
                            <motion.div
                              initial={{ opacity: 0, height: 0 }}
                              animate={{ opacity: 1, height: "auto" }}
                              exit={{ opacity: 0, height: 0 }}
                              transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
                              className="overflow-hidden"
                            >
                              <div className="mt-3 space-y-2.5 border-t border-white/[0.06] pt-3">
                                <label className="block">
                                  <span className="label">Title</span>
                                  <input
                                    value={draft.title}
                                    onChange={(e) => setEditing((prev) => ({ ...prev, [rec.id]: { ...draft, title: e.target.value } }))}
                                    className="input text-xs"
                                  />
                                </label>
                                <label className="block">
                                  <span className="label">Description</span>
                                  <textarea
                                    value={draft.description}
                                    onChange={(e) =>
                                      setEditing((prev) => ({ ...prev, [rec.id]: { ...draft, description: e.target.value } }))
                                    }
                                    rows={4}
                                    className="input text-xs"
                                  />
                                </label>
                                <label className="block">
                                  <span className="label">Hashtags</span>
                                  <input
                                    value={draft.hashtags}
                                    onChange={(e) => setEditing((prev) => ({ ...prev, [rec.id]: { ...draft, hashtags: e.target.value } }))}
                                    className="input text-xs"
                                  />
                                </label>
                                <button onClick={() => act("save", rec)} disabled={busy !== null} className="btn-primary btn-sm">
                                  {busy === `save-${rec.id}` ? <Spinner /> : "Save metadata"}
                                </button>
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>
                    </div>
                  </Card>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}

      <Reveal delay={0.08}>
        <Card>
          <SectionTitle title="How local publishing works" subtitle="Deliberately manual — no API keys, no risk of accidental uploads" />
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["1 · Render", "The pipeline writes short.mp4, thumbnail and metadata to a folder."],
              ["2 · Download", "Grab the MP4 and copy the title, description and hashtags."],
              ["3 · Upload", "Paste them into YouTube Studio in your own browser."],
              ["4 · Confirm", "Paste the published URL back so analytics stay truthful."],
            ].map(([title, body]) => (
              <div key={title} className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
                <div className="text-[11.5px] font-semibold text-slate-200">{title}</div>
                <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{body}</div>
              </div>
            ))}
          </div>
        </Card>
      </Reveal>
    </div>
  );
}
