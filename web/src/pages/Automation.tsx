import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, type AutomationState, type Schedule } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, PageHeader, Progress, relTime, Reveal, SectionTitle, Spinner } from "../components/ui";
import { Icon } from "../components/icons";

type StatusPayload = {
  state: AutomationState;
  schedule: Schedule;
  next_publish_at: string | null;
  counts: Record<string, number>;
  uploads_today: number;
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function Automation() {
  const { notify, subscribe } = useApp();
  const [data, setData] = useState<StatusPayload | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<Schedule> | null>(null);
  const [step, setStep] = useState<{ step: string; progress: number; message: string } | null>(null);

  async function load() {
    try {
      const res = await api.get<StatusPayload>("/api/automation/status");
      setData(res);
      setForm((prev) => prev ?? res.schedule);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load automation status");
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(load, 15000);
    const unsub = subscribe((e) => {
      if (e.type === "pipeline") {
        const p = e.payload as { step?: string; progress?: number; message?: string };
        setStep({ step: p.step ?? "", progress: Number(p.progress ?? 0), message: p.message ?? "" });
      }
      if (["automation_status", "queue_update", "pipeline_done", "upload_done"].includes(e.type)) void load();
    });
    return () => {
      window.clearInterval(id);
      unsub();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function act(action: string, body?: unknown) {
    setBusy(action);
    try {
      if (action === "save") {
        await api.post("/api/schedule", form);
        notify("success", "Schedule saved");
        await load();
      } else if (action === "run-now") {
        const res = await api.post<{ results: { status: string; error?: string }[] }>("/api/automation/run-now?count=1");
        const r = res.results[0];
        if (!r) notify("info", "Nothing in the queue to process");
        else if (r.status === "FAILED") notify("error", r.error ?? "Pipeline failed");
        else notify("success", `Pipeline result: ${r.status}`);
      } else if (action === "upload-now") {
        const res = await api.post<{ result: { status: string; video_id?: string } }>("/api/automation/upload-now");
        notify("success", `Upload ${res.result.status.toLowerCase()}`);
      } else if (action === "generate-idea") {
        await api.post("/api/content/ideas", { auto: true });
        notify("success", "New idea generated");
      } else {
        await api.post(`/api/automation/${action}`, body);
        notify("info", `Automation ${action}`);
      }
      await load();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  const status = data?.state.status ?? "idle";
  const progress = step?.progress ?? data?.state.current_progress ?? 0;
  const currentStep = step?.step ?? data?.state.current_step ?? "idle";
  const running = status === "running";

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Studio"
        title="Automation control"
        subtitle="The engine runs inside the backend process and keeps working when this dashboard is closed."
        actions={
          <span
            className={cx(
              "chip",
              running
                ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                : status === "paused"
                  ? "border-amber-500/25 bg-amber-500/10 text-amber-300"
                  : "border-white/10 bg-white/5 text-slate-400",
            )}
          >
            <span className={cx("h-1.5 w-1.5 rounded-full", running ? "animate-breathe bg-emerald-400" : status === "paused" ? "bg-amber-400" : "bg-slate-500")} />
            {status}
          </span>
        }
      />

      <Reveal>
        <div className="card-lit p-5">
          <div className="relative">
            <div className="flex flex-wrap items-center gap-2">
              <button onClick={() => act("start")} disabled={busy !== null || running} className="btn-primary btn-sm">
                <Icon name="play" className="h-3 w-3" strokeWidth={2.4} />
                Start
              </button>
              <button onClick={() => act("pause")} disabled={busy !== null || !running} className="btn-ghost btn-sm">
                <Icon name="pause" className="h-3 w-3" strokeWidth={2.4} />
                Pause
              </button>
              <button onClick={() => act("stop")} disabled={busy !== null} className="btn-ghost btn-sm">
                <Icon name="stop" className="h-3 w-3" strokeWidth={2.4} />
                Stop
              </button>
              <span className="mx-1 h-5 w-px bg-white/10" />
              <button onClick={() => act("run-now")} disabled={busy !== null} className="btn-ghost btn-sm">
                {busy === "run-now" ? <Spinner /> : <Icon name="bolt" className="h-3 w-3" />}
                Run now
              </button>
              <button onClick={() => act("generate-idea")} disabled={busy !== null} className="btn-ghost btn-sm">
                <Icon name="bulb" className="h-3 w-3" />
                Generate idea
              </button>
              <button onClick={() => act("upload-now")} disabled={busy !== null} className="btn-ghost btn-sm">
                <Icon name="upload" className="h-3 w-3" />
                Upload now
              </button>
              <span className="ml-auto text-[11px] text-slate-500">
                next publish {data?.next_publish_at ? relTime(data.next_publish_at) : "not scheduled"}
              </span>
            </div>

            <div className="mt-5 rounded-xl border border-white/[0.06] bg-ink-950/40 p-4">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold capitalize text-slate-200">{currentStep.replaceAll("_", " ")}</span>
                <span className="numeric text-slate-500">{Math.round(progress)}%</span>
              </div>
              <Progress value={progress} className="mt-2.5" />
              {step?.message && <div className="mt-2 text-[11px] text-slate-500">{step.message}</div>}
            </div>

            <div className="mt-3 grid gap-2 sm:grid-cols-4">
              {[
                ["Uploaded today", `${data?.uploads_today ?? 0} / ${data?.schedule.videos_per_day ?? 1}`, "upload"],
                ["Ready to upload", String(data?.counts.READY_TO_UPLOAD ?? 0), "bookmark"],
                [
                  "In production",
                  String(
                    (data?.counts.GENERATING_AUDIO ?? 0) +
                      (data?.counts.GENERATING_VISUALS ?? 0) +
                      (data?.counts.RENDERING ?? 0) +
                      (data?.counts.RESEARCHING ?? 0),
                  ),
                  "bolt",
                ],
                ["Failed", String(data?.counts.FAILED ?? 0), "alert"],
              ].map(([label, value, icon]) => (
                <div
                  key={label}
                  className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2.5 transition-colors hover:border-white/[0.12]"
                >
                  <div className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-slate-600">
                    <Icon name={icon as "upload"} className="h-3 w-3" />
                    {label}
                  </div>
                  <div className="numeric mt-1 text-[15px] font-bold text-slate-200">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Reveal>

      {form && (
        <Reveal delay={0.06}>
          <Card>
            <SectionTitle title="Publishing schedule" subtitle="Applied by the background engine every 20 seconds" />
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <span className="label">Automation</span>
                <button
                  onClick={() => setForm({ ...form, enabled: form.enabled ? 0 : 1 })}
                  className={cx(
                    "flex w-full items-center justify-between rounded-xl border px-3.5 py-2.5 text-sm font-semibold transition-all duration-200",
                    form.enabled
                      ? "border-emerald-500/35 bg-emerald-500/10 text-emerald-200"
                      : "border-white/10 text-slate-400 hover:border-white/20",
                  )}
                >
                  {form.enabled ? "Enabled" : "Disabled"}
                  <span className={cx("h-2 w-2 rounded-full", form.enabled ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" : "bg-slate-600")} />
                </button>
              </div>
              <div>
                <span className="label">Approval mode</span>
                <button
                  onClick={() => setForm({ ...form, approval_mode: form.approval_mode ? 0 : 1 })}
                  className={cx(
                    "w-full rounded-xl border px-3.5 py-2.5 text-sm font-semibold transition-all duration-200",
                    form.approval_mode
                      ? "border-amber-500/35 bg-amber-500/10 text-amber-200"
                      : "border-white/10 text-slate-400 hover:border-white/20",
                  )}
                >
                  {form.approval_mode ? "Approval required" : "Fully automatic"}
                </button>
              </div>
              <div>
                <span className="label">Videos per day</span>
                <input
                  type="number"
                  min={1}
                  max={12}
                  className="input"
                  value={form.videos_per_day ?? 1}
                  onChange={(e) => setForm({ ...form, videos_per_day: Number(e.target.value) })}
                />
              </div>
              <div>
                <span className="label">Visibility</span>
                <select className="input" value={form.visibility ?? "private"} onChange={(e) => setForm({ ...form, visibility: e.target.value })}>
                  <option value="private">Private (recommended)</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="public">Public</option>
                </select>
              </div>
              <div>
                <span className="label">Publish times</span>
                <input
                  className="input"
                  value={(form.publish_times ?? ["19:00"]).join(", ")}
                  onChange={(e) => setForm({ ...form, publish_times: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                  placeholder="19:00, 21:30"
                />
              </div>
              <div>
                <span className="label">Time zone</span>
                <input className="input" value={form.timezone ?? "UTC"} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
              </div>
              <div>
                <span className="label">Min gap (minutes)</span>
                <input
                  type="number"
                  min={15}
                  className="input"
                  value={form.min_gap_minutes ?? 90}
                  onChange={(e) => setForm({ ...form, min_gap_minutes: Number(e.target.value) })}
                />
              </div>
              <div>
                <span className="label">Quiet hours</span>
                <div className="flex gap-2">
                  <input className="input" placeholder="22:00" value={form.quiet_start ?? ""} onChange={(e) => setForm({ ...form, quiet_start: e.target.value || null })} />
                  <input className="input" placeholder="07:00" value={form.quiet_end ?? ""} onChange={(e) => setForm({ ...form, quiet_end: e.target.value || null })} />
                </div>
              </div>
            </div>

            <div className="mt-4">
              <span className="label">Days of week</span>
              <div className="flex flex-wrap gap-1.5">
                {DAYS.map((day, i) => {
                  const value = i + 1;
                  const on = (form.days_of_week ?? [1, 2, 3, 4, 5, 6, 7]).includes(value);
                  return (
                    <motion.button
                      key={day}
                      whileTap={{ scale: 0.94 }}
                      onClick={() => {
                        const set = new Set(form.days_of_week ?? [1, 2, 3, 4, 5, 6, 7]);
                        if (set.has(value)) set.delete(value);
                        else set.add(value);
                        setForm({ ...form, days_of_week: [...set].sort() });
                      }}
                      className={cx(
                        "rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all duration-200",
                        on
                          ? "border-violet-500/40 bg-violet-500/15 text-violet-200 shadow-[0_0_0_1px_rgba(139,92,246,0.1)]"
                          : "border-white/10 text-slate-500 hover:border-white/20 hover:text-slate-300",
                      )}
                    >
                      {day}
                    </motion.button>
                  );
                })}
              </div>
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
              <div className="text-[11px] text-slate-500">
                Next slot: {data?.next_publish_at ? new Date(data.next_publish_at).toLocaleString() : "none"}
              </div>
              <button onClick={() => act("save")} disabled={busy === "save"} className="btn-primary btn-sm">
                {busy === "save" ? <Spinner /> : <Icon name="check" className="h-3.5 w-3.5" strokeWidth={2.4} />}
                Save schedule
              </button>
            </div>
          </Card>
        </Reveal>
      )}

      <Reveal delay={0.12}>
        <Card>
          <SectionTitle title="Pipeline stages" subtitle="Each stage writes real artifacts to disk" />
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Research", "Wikipedia, news RSS, Reddit, YouTube"],
              ["Script", "Local model or template writer"],
              ["Audio", "Piper / SAPI / Edge TTS"],
              ["Visuals", "Procedural posters at 1080×1920"],
              ["Render", "FFmpeg scenes + captions + music"],
              ["Quality", "Weighted 13-check score"],
              ["Package", "MP4, thumb, title, description"],
              ["Confirm", "You paste the real YouTube URL"],
            ].map(([name, detail]) => (
              <div
                key={name}
                className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2.5 transition-colors hover:border-white/[0.12] hover:bg-white/[0.035]"
              >
                <div className="text-[11.5px] font-semibold text-slate-200">{name}</div>
                <div className="mt-0.5 text-[10px] leading-relaxed text-slate-500">{detail}</div>
              </div>
            ))}
          </div>
        </Card>
      </Reveal>
    </div>
  );
}
