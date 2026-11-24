import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { api, type Idea, type Project, type QualityReport, type Scene } from "../lib/api";
import { useApp } from "../lib/store";
import { Card, cx, Empty, PageHeader, Progress, Reveal, ScoreRing, Spinner, StatusChip } from "../components/ui";
import { Icon } from "../components/icons";

type ProjectPayload = {
  project: Project | null;
  scenes: Scene[];
  render_jobs: { id: number; preset: string; status: string; progress: number; step: string | null; error: string | null; log_path: string | null }[];
  video_url: string | null;
  music_url: string | null;
};

const PRESETS = [
  { key: "fast", label: "Fast (720p)" },
  { key: "balanced", label: "Balanced (1080p)" },
  { key: "high", label: "High quality" },
  { key: "lowend", label: "Low-end PC (540p)" },
];

const CAPTION_STYLES = [
  ["mrbeast", "MrBeast emphasis"],
  ["minimal-cinematic", "Minimal cinematic"],
  ["clean-educational", "Clean educational"],
  ["gaming", "Gaming"],
  ["neon", "Neon"],
  ["documentary", "Documentary"],
  ["modern-bold", "Modern bold"],
];

export default function VideoStudio() {
  const { notify, subscribe } = useApp();
  const [params, setParams] = useSearchParams();
  const ideaId = params.get("idea");
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [payload, setPayload] = useState<ProjectPayload | null>(null);
  const [report, setReport] = useState<QualityReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [preset, setPreset] = useState("balanced");
  const [captionStyle, setCaptionStyle] = useState("modern-bold");
  const [progress, setProgress] = useState<{ step: string; pct: number } | null>(null);

  const loadIdeas = useCallback(async () => {
    try {
      const data = await api.get<{ ideas: Idea[] }>("/api/content/ideas?limit=100");
      setIdeas(data.ideas);
      if (!ideaId && data.ideas.length > 0) setParams({ idea: String(data.ideas[0].id) }, { replace: true });
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load ideas");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadProject = useCallback(async (id: number) => {
    try {
      const data = await api.get<ProjectPayload>(`/api/video/ideas/${id}/project`);
      setPayload(data);
      setReport(data.project?.quality_report ?? null);
    } catch {
      setPayload(null);
    }
  }, []);

  useEffect(() => {
    void loadIdeas();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (ideaId) void loadProject(Number(ideaId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ideaId]);

  useEffect(() => {
    const unsub = subscribe((e) => {
      if (e.type === "pipeline") {
        const p = e.payload as { step?: string; progress?: number };
        setProgress({ step: p.step ?? "", pct: Number(p.progress ?? 0) });
      }
      if (["pipeline_done", "pipeline_error"].includes(e.type) && ideaId) void loadProject(Number(ideaId));
    });
    return unsub;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ideaId]);

  async function produce(force: boolean) {
    if (!ideaId) return;
    setBusy("produce");
    setProgress({ step: "starting", pct: 0 });
    try {
      const res = await api.post<{ result: { status: string; report?: QualityReport } }>(`/api/video/ideas/${ideaId}/produce`, {
        force,
        approve_script: true,
      });
      if (res.result.report) setReport(res.result.report);
      notify("success", `Pipeline finished: ${res.result.status}`);
      await loadProject(Number(ideaId));
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Production failed");
    } finally {
      setBusy(null);
      setProgress(null);
    }
  }

  async function rerender() {
    if (!ideaId) return;
    setBusy("render");
    try {
      await api.post(`/api/video/ideas/${ideaId}/rerender`, { preset, subtitle_style: captionStyle });
      notify("success", "Re-render complete");
      await loadProject(Number(ideaId));
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Render failed");
    } finally {
      setBusy(null);
    }
  }

  async function recheck() {
    if (!ideaId) return;
    setBusy("quality");
    try {
      const res = await api.post<{ report: QualityReport }>(`/api/video/ideas/${ideaId}/quality`);
      setReport(res.report);
      notify("success", `Quality score ${res.report.score}`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Quality check failed");
    } finally {
      setBusy(null);
    }
  }

  async function publishNow() {
    setBusy("upload");
    try {
      const res = await api.post<{ result: { status: string; video_id?: string } }>("/api/automation/upload-now");
      notify("success", `${res.result.status}${res.result.video_id ? ` · ${res.result.video_id}` : ""}`);
      if (ideaId) await loadProject(Number(ideaId));
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(null);
    }
  }

  const scenes = payload?.scenes ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Studio"
        title="Video studio"
        subtitle="Render, inspect the quality report, and preview before packaging."
        actions={
          <select className="input w-full sm:w-72" value={ideaId ?? ""} onChange={(e) => setParams({ idea: e.target.value })}>
            <option value="">Select an idea</option>
            {ideas.map((i) => (
              <option key={i.id} value={i.id}>
                {i.topic.slice(0, 60)}
              </option>
            ))}
          </select>
        }
      />

      {!ideaId ? (
        <Empty title="Select an idea" body="Choose an idea to render its video." icon="film" />
      ) : (
        <div className="grid gap-5 xl:grid-cols-[360px_1fr]">
          <div className="space-y-4">
            <Reveal>
              <Card className="p-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-[13px] font-semibold text-white">Preview</h2>
                  {payload?.project && <StatusChip status={payload.project.status} />}
                </div>
                <div className="mt-3 overflow-hidden rounded-xl border border-white/10 bg-black shadow-card">
                  {payload?.video_url ? (
                    <video key={payload.video_url} src={payload.video_url} controls className="aspect-[9/16] w-full" />
                  ) : (
                    <div className="relative grid aspect-[9/16] place-items-center overflow-hidden px-6 text-center">
                      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-violet-600/10 via-transparent to-cyan-500/10" />
                      <div className="relative">
                        <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl border border-white/10 bg-white/[0.04] text-slate-500">
                          <Icon name="film" className="h-5 w-5" />
                        </span>
                        <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                          No rendered video yet.
                          <br />
                          Run production to generate one.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
                {payload?.video_url && (
                  <a href={payload.video_url} download className="btn-ghost btn-sm mt-2 w-full">
                    <Icon name="download" className="h-3 w-3" strokeWidth={2.2} />
                    Download MP4
                  </a>
                )}
              </Card>
            </Reveal>

            <Reveal delay={0.05}>
              <Card className="p-4">
                <h2 className="text-[13px] font-semibold text-white">Render settings</h2>
                <div className="mt-3 space-y-2.5">
                  <div>
                    <span className="label">Preset</span>
                    <select className="input" value={preset} onChange={(e) => setPreset(e.target.value)}>
                      {PRESETS.map((p) => (
                        <option key={p.key} value={p.key}>
                          {p.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <span className="label">Caption style</span>
                    <select className="input" value={captionStyle} onChange={(e) => setCaptionStyle(e.target.value)}>
                      {CAPTION_STYLES.map(([k, label]) => (
                        <option key={k} value={k}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button onClick={rerender} disabled={busy !== null || !payload?.video_url} className="btn-ghost btn-sm w-full">
                    {busy === "render" ? <Spinner /> : <Icon name="refresh" className="h-3 w-3" />}
                    Re-render with these settings
                  </button>
                </div>
              </Card>
            </Reveal>

            <Reveal delay={0.1}>
              <Card className="p-4">
                <h2 className="text-[13px] font-semibold text-white">Actions</h2>
                <div className="mt-3 grid gap-2">
                  <button onClick={() => produce(false)} disabled={busy !== null} className="btn-primary btn-sm">
                    {busy === "produce" ? <Spinner /> : <Icon name="play" className="h-3 w-3" strokeWidth={2.4} />}
                    Run full pipeline
                  </button>
                  <button onClick={() => produce(true)} disabled={busy !== null} className="btn-ghost btn-sm">
                    Force regenerate all steps
                  </button>
                  <button onClick={recheck} disabled={busy !== null || !payload?.video_url} className="btn-ghost btn-sm">
                    {busy === "quality" ? <Spinner /> : <Icon name="shield" className="h-3 w-3" />}
                    Re-run quality check
                  </button>
                  <button onClick={publishNow} disabled={busy !== null} className="btn-ghost btn-sm">
                    {busy === "upload" ? <Spinner /> : <Icon name="upload" className="h-3 w-3" />}
                    Upload now
                  </button>
                </div>
                {progress && (
                  <div className="mt-3 rounded-lg border border-violet-500/20 bg-violet-500/[0.06] p-2.5">
                    <div className="flex justify-between text-2xs text-slate-400">
                      <span className="capitalize">{progress.step.replaceAll("_", " ")}</span>
                      <span className="numeric">{Math.round(progress.pct)}%</span>
                    </div>
                    <Progress value={progress.pct} className="mt-1.5" />
                  </div>
                )}
              </Card>
            </Reveal>
          </div>

          <div className="space-y-4">
            {report ? (
              <Reveal>
                <Card>
                  <div className="flex flex-wrap items-center gap-4">
                    <ScoreRing score={report.score} size={88} label="score" />
                    <div className="min-w-0 flex-1">
                      <h2 className="text-[13.5px] font-semibold text-white">Quality report</h2>
                      <p className="mt-0.5 text-[11px] text-slate-400">
                        Threshold {report.threshold} · {report.width}×{report.height} · {report.duration.toFixed(1)}s
                      </p>
                      <div className="mt-2.5">
                        <Progress value={report.score} />
                      </div>
                      <div className="mt-1.5 text-2xs text-slate-500">
                        {report.score >= report.threshold ? "Passes the gate" : "Below threshold — review suggestions"}
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-1.5 sm:grid-cols-2">
                    {report.checks.map((c, i) => (
                      <motion.div
                        key={c.name}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: Math.min(i * 0.02, 0.25) }}
                        className="flex items-center gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-1.5"
                      >
                        <span
                          className={cx(
                            "h-1.5 w-1.5 shrink-0 rounded-full",
                            c.score >= 80 ? "bg-emerald-400" : c.score >= 60 ? "bg-amber-400" : "bg-rose-400",
                          )}
                        />
                        <span className="flex-1 truncate text-[11px] text-slate-300">{c.name}</span>
                        <span className="numeric text-2xs text-slate-500">{Math.round(c.score)}</span>
                      </motion.div>
                    ))}
                  </div>
                  {report.suggestions.length > 0 && (
                    <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] p-2.5">
                      <div className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-amber-300">
                        <Icon name="alert" className="h-3 w-3" />
                        Suggestions
                      </div>
                      <ul className="mt-1.5 space-y-1 text-[11px] leading-relaxed text-amber-200/80">
                        {report.suggestions.map((s) => (
                          <li key={s} className="flex gap-1.5">
                            <span className="text-amber-400/60">·</span>
                            {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </Card>
              </Reveal>
            ) : (
              <Reveal>
                <Card>
                  <h2 className="text-[13.5px] font-semibold text-white">Quality report</h2>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                    Run the pipeline to score hook, audio, captions, resolution, timing and grounding.
                  </p>
                </Card>
              </Reveal>
            )}

            <Reveal delay={0.06}>
              <Card>
                <div className="flex items-center justify-between">
                  <h2 className="text-[13.5px] font-semibold text-white">Scene timeline</h2>
                  <span className="text-2xs text-slate-500">{scenes.length} scenes</span>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {scenes.map((scene, i) => (
                    <motion.div
                      key={scene.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: Math.min(i * 0.04, 0.25), duration: 0.35 }}
                      className="group overflow-hidden rounded-xl border border-white/[0.05] bg-white/[0.02] transition-colors hover:border-white/[0.12]"
                    >
                      <div className="aspect-[9/16] overflow-hidden bg-ink-800">
                        {scene.asset_url ? (
                          <img
                            src={scene.asset_url}
                            alt=""
                            className="h-full w-full object-cover transition-transform duration-500 ease-smooth group-hover:scale-[1.04]"
                          />
                        ) : (
                          <div className="grid h-full place-items-center text-[10px] text-slate-600">no asset</div>
                        )}
                      </div>
                      <div className="p-2">
                        <div className="flex items-center justify-between text-2xs text-slate-500">
                          <span className="font-semibold">#{scene.scene_no}</span>
                          <span className="numeric">{scene.duration.toFixed(1)}s</span>
                        </div>
                        <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-slate-400">{scene.narration}</div>
                        {scene.audio_url && <audio src={scene.audio_url} controls className="mt-1.5 h-6 w-full" />}
                      </div>
                    </motion.div>
                  ))}
                  {scenes.length === 0 && <div className="text-xs text-slate-500">No scenes yet.</div>}
                </div>
              </Card>
            </Reveal>

            {payload?.render_jobs?.length ? (
              <Reveal delay={0.1}>
                <Card>
                  <h2 className="text-[13.5px] font-semibold text-white">Render jobs</h2>
                  <div className="mt-2 space-y-1.5">
                    {payload.render_jobs.map((job) => (
                      <div
                        key={job.id}
                        className="flex items-center gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-1.5 text-[11px]"
                      >
                        <span className="font-mono text-2xs text-slate-500">#{job.id}</span>
                        <span className="text-slate-400">{job.preset}</span>
                        <span
                          className={cx(
                            "chip",
                            job.status === "done"
                              ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                              : job.status === "failed"
                                ? "border-rose-500/25 bg-rose-500/10 text-rose-300"
                                : "border-white/10 text-slate-400",
                          )}
                        >
                          {job.status}
                        </span>
                        <span className="numeric ml-auto text-slate-500">{Math.round(job.progress)}%</span>
                      </div>
                    ))}
                  </div>
                </Card>
              </Reveal>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
