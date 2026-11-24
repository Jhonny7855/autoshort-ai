import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { api, type AutomationState, type Niche, type Schedule } from "../lib/api";
import { useApp } from "../lib/store";
import {
  Card,
  cx,
  Empty,
  PageHeader,
  Progress,
  relTime,
  Reveal,
  SectionTitle,
  Stagger,
  StaggerItem,
  StatCard,
  StatusChip,
} from "../components/ui";
import { Icon } from "../components/icons";

type Overview = {
  user: { name: string | null; email: string | null; picture: string | null };
  channel: { title: string; thumbnail: string | null; subscriber_count: number | null } | null;
  niche: Niche | null;
  automation: { state: AutomationState; schedule: Schedule; next_publish_at: string | null; uploads_today: number };
  metrics: { published: number; queue: number; generating: number; failed: number; views: number };
  recent: { id: number; status: string; updated_at: string; topic: string; quality_score: number | null }[];
  latest_videos: {
    id: number;
    title: string;
    thumbnail: string | null;
    status: string;
    views: number;
    published_at: string | null;
    youtube_video_id: string;
  }[];
  upcoming: { id: number; topic: string; status: string }[];
  logs: { level: string; scope: string; message: string; created_at: string }[];
};

const STAGE_LABELS = [
  "Idea",
  "Research",
  "Script",
  "Voice",
  "Visuals",
  "Render",
  "Quality",
  "Publish",
];

export default function Dashboard() {
  const { auth, subscribe, notify } = useApp();
  const [data, setData] = useState<Overview | null>(null);
  const [pubCounts, setPubCounts] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const [overview, publish] = await Promise.all([
        api.get<Overview>("/api/dashboard/overview"),
        api.get<{ counts: Record<string, number> }>("/api/publish/summary").catch(() => null),
      ]);
      setData(overview);
      if (publish) setPubCounts(publish.counts);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load dashboard");
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(load, 20000);
    const unsub = subscribe((e) => {
      if (["automation_status", "pipeline", "queue_update", "upload_done", "pipeline_done", "pipeline_error"].includes(e.type)) {
        void load();
      }
    });
    return () => {
      window.clearInterval(id);
      unsub();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function control(action: "start" | "pause" | "stop" | "run-now" | "upload-now") {
    setBusy(action);
    try {
      if (action === "run-now") {
        const res = await api.post<{ results: { status: string; error?: string }[] }>("/api/automation/run-now?count=1");
        const r = res.results[0];
        if (!r) notify("info", "Nothing to process — queue is empty");
        else if (r.status === "FAILED") notify("error", r.error ?? "Pipeline failed");
        else notify("success", `Pipeline finished: ${r.status}`);
      } else if (action === "upload-now") {
        const res = await api.post<{ result: { status: string; video_id?: string } }>("/api/automation/upload-now");
        notify("success", `Upload ${res.result.status.toLowerCase()}${res.result.video_id ? ` · ${res.result.video_id}` : ""}`);
      } else {
        await api.post(`/api/automation/${action}`);
        notify("info", `Automation ${action === "start" ? "started" : action === "pause" ? "paused" : "stopped"}`);
      }
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  const state = data?.automation.state;
  const running = state?.status === "running";
  const progress = Math.round(state?.current_progress ?? 0);
  const activeStage = state?.current_step ? STAGE_LABELS.indexOf(stageFromStep(state.current_step)) : -1;
  const firstName = data?.user.name?.split(" ")[0] ?? auth?.user?.name?.split(" ")[0] ?? "creator";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={data?.niche ? data.niche.name : "Local workspace"}
        title={`${greeting()}, ${firstName}`}
        subtitle={
          data?.channel
            ? `${data.channel.title} · ${data.channel.subscriber_count ?? 0} subscribers`
            : "Local mode — every Short is packaged here for you to publish by hand."
        }
        actions={
          <>
            <Link to="/publishing" className="btn-ghost">
              <Icon name="upload" className="h-4 w-4" />
              Publishing queue
            </Link>
            <button onClick={() => control("run-now")} disabled={busy !== null} className="btn-ghost">
              {busy === "run-now" ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-white" /> : <Icon name="play" className="h-3.5 w-3.5" strokeWidth={2} />}
              Run now
            </button>
            {auth?.channel && (
              <button onClick={() => control("upload-now")} disabled={busy !== null} className="btn-ghost">
                Upload now
              </button>
            )}
            {running ? (
              <button onClick={() => control("pause")} disabled={busy !== null} className="btn-ghost">
                <Icon name="pause" className="h-3.5 w-3.5" strokeWidth={2} />
                Pause
              </button>
            ) : (
              <button onClick={() => control("start")} disabled={busy !== null} className="btn-primary">
                <Icon name="bolt" className="h-4 w-4" strokeWidth={1.9} />
                Start automation
              </button>
            )}
          </>
        }
      />

      <Stagger className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" step={0.055}>
        <StaggerItem>
          <StatCard
            label="Ready to publish"
            value={pubCounts?.ready ?? 0}
            accent="emerald"
            icon="upload"
            loading={!data}
            hint="Packaged and waiting for you"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Pending review"
            value={pubCounts?.pending_review ?? 0}
            accent="amber"
            icon="alert"
            loading={!data}
            hint="Needs your approval first"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard label="In queue" value={data?.metrics.queue ?? 0} accent="violet" icon="layers" loading={!data} hint="Items in the pipeline" />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Generating"
            value={data?.metrics.generating ?? 0}
            accent="cyan"
            icon="bolt"
            loading={!data}
            hint={running ? "Engine is working" : "Engine idle"}
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            label="Failed tasks"
            value={data?.metrics.failed ?? 0}
            accent={data?.metrics.failed ? "rose" : "slate"}
            icon="alert"
            loading={!data}
            hint={data?.metrics.failed ? "Check the queue for details" : "Nothing broken"}
          />
        </StaggerItem>
      </Stagger>

      <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
        <Reveal>
          <Card className="h-full">
            <SectionTitle
              title="Automation activity"
              subtitle={
                running
                  ? "Engine is working through the queue"
                  : state?.status === "paused"
                    ? "Paused by you"
                    : "Idle — press Start to begin"
              }
              action={
                <span
                  className={cx(
                    "chip",
                    running
                      ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                      : "border-white/10 bg-white/5 text-slate-400",
                  )}
                >
                  <span className={cx("h-1.5 w-1.5 rounded-full", running ? "animate-breathe bg-emerald-400" : "bg-slate-500")} />
                  {state?.status ?? "loading"}
                </span>
              }
            />

            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-semibold text-slate-200">
                  {state?.current_step?.replaceAll("_", " ") ?? "Waiting for a task"}
                </span>
                <span className="numeric text-xs text-slate-500">{progress}%</span>
              </div>
              <Progress value={progress} className="mt-2.5" />
              <div className="mt-3 flex items-center justify-between gap-1">
                {STAGE_LABELS.map((label, i) => {
                  const done = activeStage > i || (!running && progress >= 100);
                  const current = running && activeStage === i;
                  return (
                    <div key={label} className="flex min-w-0 flex-1 flex-col items-center gap-1">
                      <span
                        className={cx(
                          "h-1 w-full rounded-full transition-colors duration-500",
                          current ? "bg-violet-400" : done ? "bg-emerald-500/50" : "bg-white/[0.07]",
                        )}
                      />
                      <span
                        className={cx(
                          "hidden truncate text-[9px] uppercase tracking-wider sm:block",
                          current ? "text-violet-300" : done ? "text-emerald-400/70" : "text-slate-600",
                        )}
                      >
                        {label}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {state?.last_error && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                className="mt-3 overflow-hidden rounded-lg border border-rose-500/25 bg-rose-500/[0.07] p-2.5 text-[11px] leading-relaxed text-rose-200"
              >
                {state.last_error}
              </motion.div>
            )}

            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Info
                label="Next publish"
                value={data?.automation.next_publish_at ? relTime(data.automation.next_publish_at) : "not scheduled"}
                icon="clock"
              />
              <Info
                label="Uploaded today"
                value={`${data?.automation.uploads_today ?? 0} / ${data?.automation.schedule.videos_per_day ?? 1}`}
                icon="upload"
              />
              <Info label="Schedule" value={data?.automation.schedule.enabled ? "enabled" : "disabled"} icon="calendar" />
              <Info label="Approval" value={data?.automation.schedule.approval_mode ? "required" : "automatic"} icon="shield" />
            </div>

            <div className="mt-5 border-t border-white/[0.06] pt-4">
              <div className="mb-2.5 flex items-center justify-between">
                <span className="eyebrow">Recent events</span>
                <Link to="/logs" className="text-2xs font-semibold text-violet-300 transition hover:text-violet-200">
                  View all
                </Link>
              </div>
              <div className="space-y-0.5">
                {(data?.logs ?? []).slice(0, 6).map((log, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className="group flex items-start gap-2.5 rounded-lg px-1.5 py-1.5 transition-colors hover:bg-white/[0.03]"
                  >
                    <span
                      className={cx(
                        "mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full",
                        log.level === "error" ? "bg-rose-400" : log.level === "warn" ? "bg-amber-400" : "bg-slate-600",
                      )}
                    />
                    <span className="flex-1 text-[11.5px] leading-relaxed text-slate-400">{log.message}</span>
                    <span className="shrink-0 whitespace-nowrap text-2xs text-slate-600">{relTime(log.created_at)}</span>
                  </motion.div>
                ))}
                {!data?.logs?.length && <div className="px-1.5 text-[11px] text-slate-600">No events yet.</div>}
              </div>
            </div>
          </Card>
        </Reveal>

        <div className="space-y-5">
          <Reveal delay={0.06}>
            <Card>
              <SectionTitle
                title="Content calendar"
                subtitle="Upcoming publishing slots"
                action={
                  <Link to="/calendar" className="flex items-center gap-1 text-2xs font-semibold text-violet-300 transition hover:text-violet-200">
                    Open <Icon name="chevron" className="h-3 w-3" strokeWidth={2.4} />
                  </Link>
                }
              />
              <div className="space-y-2">
                {(data?.upcoming ?? []).length === 0 && (
                  <div className="rounded-xl border border-dashed border-white/[0.08] px-3 py-5 text-center text-[11px] text-slate-500">
                    Nothing scheduled. Start automation to fill the pipeline.
                  </div>
                )}
                {(data?.upcoming ?? []).map((item) => (
                  <div
                    key={item.id}
                    className="group flex items-center gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2 transition-colors hover:border-white/10 hover:bg-white/[0.04]"
                  >
                    <div className="min-w-0 flex-1 truncate text-[11.5px] text-slate-300">{item.topic}</div>
                    <StatusChip status={item.status} />
                  </div>
                ))}
              </div>
            </Card>
          </Reveal>

          <Reveal delay={0.12}>
            <Card>
              <SectionTitle
                title="Queue snapshot"
                subtitle="Live pipeline state"
                action={
                  <Link to="/queue" className="flex items-center gap-1 text-2xs font-semibold text-violet-300 transition hover:text-violet-200">
                    Open <Icon name="chevron" className="h-3 w-3" strokeWidth={2.4} />
                  </Link>
                }
              />
              <div className="space-y-1.5">
                {(data?.recent ?? []).slice(0, 6).map((item) => (
                  <div key={item.id} className="flex items-center gap-2 py-0.5 text-[11px]">
                    <StatusChip status={item.status} />
                    <span className="min-w-0 flex-1 truncate text-slate-400">{item.topic}</span>
                    {item.quality_score !== null && (
                      <span
                        className={cx(
                          "numeric shrink-0 text-[10.5px] font-semibold",
                          item.quality_score >= 75 ? "text-emerald-300" : "text-amber-300",
                        )}
                      >
                        {Math.round(item.quality_score)}
                      </span>
                    )}
                  </div>
                ))}
                {!data?.recent?.length && (
                  <div className="rounded-xl border border-dashed border-white/[0.08] px-3 py-5 text-center text-[11px] text-slate-500">
                    Queue is empty.
                  </div>
                )}
              </div>
            </Card>
          </Reveal>
        </div>
      </div>

      <Reveal delay={0.1}>
        <Card>
          <SectionTitle
            title="Latest videos"
            subtitle="Published from AUTOSHORT AI"
            action={
              <Link to="/published" className="flex items-center gap-1 text-2xs font-semibold text-violet-300 transition hover:text-violet-200">
                All videos <Icon name="chevron" className="h-3 w-3" strokeWidth={2.4} />
              </Link>
            }
          />
          {(data?.latest_videos ?? []).length === 0 ? (
            <Empty title="No published videos yet" body="Videos appear here after a successful YouTube upload." icon="bookmark" />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(data?.latest_videos ?? []).map((v) => (
                <a
                  key={v.id}
                  href={`https://www.youtube.com/watch?v=${v.youtube_video_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="group overflow-hidden rounded-xl border border-white/[0.06] bg-white/[0.02] transition-all duration-300 hover:-translate-y-0.5 hover:border-white/15 hover:shadow-lift"
                >
                  <div className="relative aspect-video overflow-hidden bg-ink-800">
                    {v.thumbnail ? (
                      <img
                        src={v.thumbnail}
                        alt=""
                        className="h-full w-full object-cover transition-transform duration-500 ease-smooth group-hover:scale-105"
                      />
                    ) : (
                      <div className="grid h-full place-items-center text-[11px] text-slate-600">no thumbnail</div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                  </div>
                  <div className="p-3">
                    <div className="line-clamp-2 text-[11.5px] font-semibold leading-snug text-slate-200">{v.title}</div>
                    <div className="mt-1.5 flex items-center justify-between text-2xs text-slate-500">
                      <span>{v.views} views</span>
                      <span>{relTime(v.published_at)}</span>
                    </div>
                  </div>
                </a>
              ))}
            </div>
          )}
        </Card>
      </Reveal>
    </div>
  );
}

function Info({ label, value, icon }: { label: string; value: string; icon: "clock" | "upload" | "calendar" | "shield" }) {
  return (
    <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-2 transition-colors hover:border-white/10">
      <div className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-slate-600">
        <Icon name={icon} className="h-3 w-3" />
        {label}
      </div>
      <div className="mt-1 truncate text-[11px] font-semibold text-slate-300">{value}</div>
    </div>
  );
}

function stageFromStep(step: string): string {
  const s = step.toLowerCase();
  if (s.includes("idea")) return "Idea";
  if (s.includes("research")) return "Research";
  if (s.includes("script") || s.includes("writ")) return "Script";
  if (s.includes("audio") || s.includes("voice") || s.includes("tts")) return "Voice";
  if (s.includes("visual") || s.includes("image")) return "Visuals";
  if (s.includes("render") || s.includes("mux")) return "Render";
  if (s.includes("quality") || s.includes("check")) return "Quality";
  if (s.includes("upload") || s.includes("publish")) return "Publish";
  return "";
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}
