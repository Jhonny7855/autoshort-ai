import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api, type Channel, type Niche } from "../lib/api";
import { useApp } from "../lib/store";
import { cx, Progress, Spinner } from "../components/ui";
import { Icon } from "../components/icons";

type Check = {
  google: boolean;
  ai: { reachable: boolean; models: number };
  tts: string[];
  ffmpeg: boolean;
  channel: Channel | null;
  niche: Niche | null;
  ready: boolean;
};

const STEPS = ["Welcome", "Google", "Channel", "Niche", "Language", "Voice", "Style", "Schedule", "Mode", "Test", "Launch"];

export default function Onboarding() {
  const nav = useNavigate();
  const { auth, refreshAuth, notify } = useApp();
  const [step, setStep] = useState(0);
  const [check, setCheck] = useState<Check | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [niches, setNiches] = useState<Niche[]>([]);
  const [scoring, setScoring] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const [language, setLanguage] = useState("en");
  const [voice, setVoice] = useState("en-US-GuyNeural");
  const [voiceProvider, setVoiceProvider] = useState("auto");
  const [style, setStyle] = useState("energetic-explainer");
  const [seconds, setSeconds] = useState(45);
  const [videosPerDay, setVideosPerDay] = useState(1);
  const [publishTime, setPublishTime] = useState("19:00");
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [approvalMode, setApprovalMode] = useState(true);
  const [voices, setVoices] = useState<{ edge: { id: string; label: string }[]; sapi: { id: string; label: string }[] } | null>(null);
  const [testResult, setTestResult] = useState<{ tts?: string; ffmpeg?: string; youtube?: string; ai?: string }>({});

  useEffect(() => {
    if (!auth?.authenticated) {
      nav("/");
      return;
    }
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth?.authenticated]);

  async function loadAll() {
    try {
      const [c, n, v] = await Promise.all([
        api.get<{ channels: Channel[] }>("/api/auth/channels"),
        api.get<{ niches: Niche[] }>("/api/ai/niches"),
        api.get<{ voices: { edge: { id: string; label: string }[]; sapi: { id: string; label: string }[] } }>("/api/content/voices"),
      ]);
      setChannels(c.channels);
      setNiches(n.niches);
      setVoices(v.voices);
      const oc = await api.get<Check>("/api/system/onboarding/check");
      setCheck(oc);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Failed to load onboarding data");
    }
  }

  async function syncChannels() {
    setBusy("sync");
    try {
      const data = await api.post<{ channels: Channel[] }>("/api/auth/channels/sync");
      setChannels(data.channels);
      await refreshAuth();
      notify("success", `Found ${data.channels.length} channel(s)`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Channel sync failed");
    } finally {
      setBusy(null);
    }
  }

  async function selectChannel(ch: Channel) {
    setBusy(`ch-${ch.id}`);
    try {
      await api.post("/api/auth/channels/select", { channel_row_id: ch.id });
      await refreshAuth();
      notify("success", `Linked ${ch.title}`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Could not select channel");
    } finally {
      setBusy(null);
    }
  }

  async function scoreNiches() {
    setScoring(true);
    try {
      const data = await api.post<{ niches: Niche[] }>("/api/ai/niches/score");
      setNiches(data.niches);
      notify("success", "Niche scores updated");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Scoring failed — using heuristic scores");
    } finally {
      setScoring(false);
    }
  }

  async function activateNiche(n: Niche) {
    setBusy(`niche-${n.id}`);
    try {
      await api.post("/api/ai/niches/activate", { niche_id: n.id });
      setNiches((prev) => prev.map((x) => ({ ...x, active: x.id === n.id ? 1 : 0 })));
      notify("success", `${n.name} is now your active niche`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Could not activate niche");
    } finally {
      setBusy(null);
    }
  }

  async function runTests() {
    setBusy("test");
    const out: typeof testResult = {};
    try {
      const r = await api.post<{ ok: boolean; error?: string; provider?: string }>("/api/system/test/tts");
      out.tts = r.ok ? `OK (${r.provider})` : r.error ?? "failed";
    } catch (err) {
      out.tts = err instanceof Error ? err.message : "failed";
    }
    try {
      const r = await api.post<{ ok: boolean }>("/api/system/test/ffmpeg");
      out.ffmpeg = r.ok ? "OK" : "FFmpeg missing";
    } catch {
      out.ffmpeg = "failed";
    }
    try {
      const r = await api.post<{ ok: boolean; error?: string; channels?: number }>("/api/system/test/youtube");
      out.youtube = r.ok ? `OK (${r.channels} channel)` : r.error ?? "not linked";
    } catch (err) {
      out.youtube = err instanceof Error ? err.message : "not linked";
    }
    try {
      const r = await api.post<{ ok: boolean; error?: string }>("/api/ai/test");
      out.ai = r.ok ? "OK" : r.error ?? "no model";
    } catch (err) {
      out.ai = err instanceof Error ? err.message : "no model";
    }
    setTestResult(out);
    setBusy(null);
  }

  async function finish() {
    setBusy("finish");
    try {
      await api.post("/api/ai/settings", { key: "language", value: language });
      await api.post("/api/ai/settings", { key: "tts_voice", value: voice });
      await api.post("/api/ai/settings", { key: "tts_provider", value: voiceProvider });
      await api.post("/api/ai/settings", { key: "content_style", value: style });
      await api.post("/api/ai/settings", { key: "script_seconds", value: seconds });
      await api.post("/api/ai/settings", { key: "approval_required", value: approvalMode });
      await api.post("/api/schedule", {
        enabled: false,
        approval_mode: approvalMode,
        videos_per_day: videosPerDay,
        publish_times: [publishTime],
        timezone,
        visibility: "private",
      });
      await refreshAuth();
      notify("success", "Setup complete. Automation is idle until you press Start.");
      nav("/dashboard");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Could not save settings");
    } finally {
      setBusy(null);
    }
  }

  const activeNiche = niches.find((n) => n.active === 1);
  const selectedChannel = channels.find((c) => c.is_selected === 1);
  const canAdvance = () => {
    if (step === 2) return Boolean(selectedChannel);
    if (step === 3) return Boolean(activeNiche);
    return true;
  };

  const progress = ((step + 1) / STEPS.length) * 100;

  return (
    <div className="relative mx-auto max-w-4xl px-5 py-10">
      <div className="pointer-events-none absolute -top-24 left-1/2 h-64 w-[36rem] -translate-x-1/2 rounded-full bg-violet-600/10 blur-3xl" />

      <div className="relative mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="relative grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-violet-600 to-cyan-500 text-sm font-black text-white shadow-glow">
            AS
            <span className="absolute inset-0 overflow-hidden rounded-2xl">
              <span className="absolute inset-y-0 -left-full w-1/2 animate-sweep bg-gradient-to-r from-transparent via-white/30 to-transparent" />
            </span>
          </div>
          <div>
            <div className="text-sm font-bold text-white">AUTOSHORT AI setup</div>
            <div className="text-[11px] text-slate-500">
              Step {step + 1} of {STEPS.length} · {STEPS[step]}
            </div>
          </div>
        </div>
        <div className="w-full max-w-xs">
          <div className="mb-1.5 flex items-center justify-between text-2xs text-slate-500">
            <span>Progress</span>
            <span className="numeric">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} />
        </div>
      </div>

      <div className="mb-6 flex gap-1.5">
        {STEPS.map((s, i) => (
          <button
            key={s}
            onClick={() => i <= step && setStep(i)}
            disabled={i > step}
            aria-label={s}
            title={s}
            className={cx(
              "h-1 flex-1 rounded-full transition-all duration-500 ease-smooth",
              i < step ? "bg-violet-500" : i === step ? "bg-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.6)]" : "bg-white/10",
              i <= step ? "cursor-pointer" : "cursor-default",
            )}
          />
        ))}
      </div>

      <div className="card-lit relative p-7">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
          >
            {step === 0 && (
              <div>
                <h1 className="text-2xl font-bold text-white">Welcome to AUTOSHORT AI</h1>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-400">
                  This wizard configures a complete autonomous Shorts workflow on your machine. It takes about two
                  minutes. Everything here is free — local AI, local voice, local rendering, and official YouTube upload.
                </p>
                <ul className="mt-5 grid gap-2 text-sm text-slate-300 sm:grid-cols-2">
                  {[
                    "Research + script generation with local models",
                    "Offline narration with word-level captions",
                    "1080x1920 render with motion and music",
                    "Quality gate before anything is uploaded",
                    "Private uploads by default",
                    "Runs in the background without the dashboard open",
                  ].map((line, i) => (
                    <motion.li
                      key={line}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.35, delay: 0.06 * i, ease: [0.16, 1, 0.3, 1] }}
                      className="flex items-start gap-2 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2"
                    >
                      <Icon name="check" className="mt-0.5 h-3 w-3 shrink-0 text-cyan-300" strokeWidth={2.6} />
                      {line}
                    </motion.li>
                  ))}
                </ul>
              </div>
            )}

            {step === 1 && (
              <div>
                <h1 className="text-xl font-bold text-white">Google account</h1>
                <p className="mt-2 text-sm text-slate-400">
                  AUTOSHORT AI uses official Google OAuth 2.0. It never sees your password and cannot bypass any Google
                  security check.
                </p>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className={cx("rounded-xl border p-4", auth?.google_linked ? "border-emerald-500/30 bg-emerald-500/5" : "border-white/10 bg-white/[0.02]")}>
                    <div className="eyebrow">Account</div>
                    <div className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-white">
                      <span className={cx("h-1.5 w-1.5 rounded-full", auth?.google_linked ? "bg-emerald-400" : "bg-slate-600")} />
                      {auth?.user?.email ?? "Local mode (no Google account)"}
                    </div>
                    <div className="mt-1 text-[11px] text-slate-500">
                      {auth?.google_linked ? "Google tokens stored encrypted" : "Uploads disabled until Google is linked"}
                    </div>
                  </div>
                  <div className={cx("rounded-xl border p-4", check?.google ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5")}>
                    <div className="eyebrow">OAuth app</div>
                    <div className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-white">
                      <span className={cx("h-1.5 w-1.5 rounded-full", check?.google ? "bg-emerald-400" : "bg-amber-400")} />
                      {check?.google ? "Configured" : "Not configured"}
                    </div>
                    <div className="mt-1 text-[11px] text-slate-500">
                      {check?.google ? "Client ID + secret found in .env" : "Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env"}
                    </div>
                  </div>
                </div>
                {!auth?.google_linked && check?.google && (
                  <button onClick={() => (window.location.href = "/api/auth/google/start?mode=link")} className="btn-primary mt-5">
                    <Icon name="external" className="h-4 w-4" />
                    Link Google account
                  </button>
                )}
                <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                  Skipping is fine — local publishing works without a Google account, and you can link one later from
                  Settings.
                </p>
              </div>
            )}

            {step === 2 && (
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h1 className="text-xl font-bold text-white">Select your channel</h1>
                  <button onClick={syncChannels} disabled={busy === "sync"} className="btn-ghost btn-sm">
                    {busy === "sync" ? <Spinner /> : <Icon name="refresh" className="h-3.5 w-3.5" />}
                    Refresh channels
                  </button>
                </div>
                {channels.length === 0 ? (
                  <div className="mt-4 rounded-xl border border-amber-500/25 bg-amber-500/5 p-4">
                    <div className="flex items-center gap-1.5 text-sm font-semibold text-amber-200">
                      <Icon name="alert" className="h-3.5 w-3.5" />
                      No channels found
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-amber-200/70">
                      Google does not expose a public API to create channels. Create one in YouTube Studio with the same
                      Google account, then press Refresh channels.
                    </p>
                    <a href="https://www.youtube.com/create_channel" target="_blank" rel="noreferrer" className="btn-ghost btn-sm mt-3">
                      <Icon name="external" className="h-3 w-3" />
                      Open official channel creation
                    </a>
                  </div>
                ) : (
                  <div className="mt-4 grid gap-2.5">
                    {channels.map((ch, i) => (
                      <motion.button
                        key={ch.id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.35, delay: i * 0.04, ease: [0.16, 1, 0.3, 1] }}
                        onClick={() => selectChannel(ch)}
                        disabled={busy === `ch-${ch.id}`}
                        className={cx(
                          "flex items-center gap-3 rounded-xl border p-3 text-left transition-all duration-300 ease-smooth",
                          ch.is_selected
                            ? "border-violet-500/50 bg-violet-500/10"
                            : "border-white/10 bg-white/[0.02] hover:-translate-y-0.5 hover:border-white/20",
                        )}
                      >
                        {ch.thumbnail ? (
                          <img src={ch.thumbnail} alt="" className="h-10 w-10 rounded-full" />
                        ) : (
                          <div className="grid h-10 w-10 place-items-center rounded-full bg-white/10 text-xs font-bold">
                            {ch.title?.[0] ?? "?"}
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-semibold text-white">{ch.title}</div>
                          <div className="text-[11px] text-slate-500">
                            {ch.subscriber_count ?? 0} subscribers · {ch.video_count ?? 0} videos
                          </div>
                        </div>
                        {ch.is_selected === 1 && (
                          <span className="chip border-violet-500/40 bg-violet-500/15 text-violet-200">
                            <Icon name="check" className="h-2.5 w-2.5" strokeWidth={3} />
                            Selected
                          </span>
                        )}
                      </motion.button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {step === 3 && (
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h1 className="text-xl font-bold text-white">Choose a niche</h1>
                  <button onClick={scoreNiches} disabled={scoring} className="btn-ghost btn-sm">
                    {scoring ? <Spinner /> : <Icon name="sparkles" className="h-3.5 w-3.5" />}
                    Score with AI
                  </button>
                </div>
                <p className="mt-1 text-sm text-slate-400">Scores weigh demand, competition, Shorts fit, repeatability and visual potential.</p>
                <div className="scrollbar-thin mt-4 grid max-h-[380px] gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
                  {niches.map((n, i) => (
                    <motion.button
                      key={n.id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.32, delay: Math.min(i * 0.03, 0.3), ease: [0.16, 1, 0.3, 1] }}
                      onClick={() => activateNiche(n)}
                      className={cx(
                        "rounded-xl border p-3 text-left transition-all duration-300 ease-smooth",
                        n.active ? "border-violet-500/50 bg-violet-500/10" : "border-white/10 bg-white/[0.02] hover:border-white/20",
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-sm font-semibold text-white">{n.name}</div>
                        <span className="chip border-cyan-500/30 bg-cyan-500/10 text-cyan-300">{Math.round(n.total_score)}</span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-400">{n.description}</p>
                      {n.rationale && <p className="mt-1.5 line-clamp-2 text-2xs italic text-slate-500">{n.rationale}</p>}
                    </motion.button>
                  ))}
                </div>
              </div>
            )}

            {step === 4 && (
              <div>
                <h1 className="text-xl font-bold text-white">Video language</h1>
                <p className="mt-1 text-sm text-slate-400">Used for scripts and narration.</p>
                <div className="mt-4 grid gap-2 sm:grid-cols-3">
                  {[
                    ["en", "English"],
                    ["hi", "Hindi"],
                    ["es", "Spanish"],
                    ["fr", "French"],
                    ["de", "German"],
                    ["pt", "Portuguese"],
                  ].map(([code, label]) => (
                    <button
                      key={code}
                      onClick={() => setLanguage(code)}
                      className={cx(
                        "rounded-xl border px-4 py-3 text-sm font-semibold transition-all duration-300 ease-smooth",
                        language === code
                          ? "border-violet-500/50 bg-violet-500/10 text-white"
                          : "border-white/10 text-slate-300 hover:-translate-y-0.5 hover:border-white/20",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="mt-6">
                  <span className="label">Default Short length</span>
                  <div className="flex gap-2">
                    {[15, 30, 45, 60].map((s) => (
                      <button
                        key={s}
                        onClick={() => setSeconds(s)}
                        className={cx(
                          "rounded-lg border px-4 py-2 text-sm font-semibold transition-all duration-300 ease-smooth",
                          seconds === s ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-200" : "border-white/10 text-slate-400 hover:border-white/20",
                        )}
                      >
                        {s}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {step === 5 && (
              <div>
                <h1 className="text-xl font-bold text-white">Choose a voice</h1>
                <p className="mt-1 text-sm text-slate-400">
                  Provider chain: {check?.tts?.length ? check.tts.join(" → ") : "detecting"}. Offline engines are tried first.
                </p>
                <div className="mt-4">
                  <span className="label">Provider</span>
                  <select className="input" value={voiceProvider} onChange={(e) => setVoiceProvider(e.target.value)}>
                    <option value="auto">Automatic (recommended)</option>
                    <option value="piper">Piper (offline neural)</option>
                    <option value="sapi">Windows speech (offline)</option>
                    <option value="edge">Edge TTS (free, needs internet)</option>
                  </select>
                </div>
                <div className="mt-4">
                  <span className="label">Voice</span>
                  <select className="input" value={voice} onChange={(e) => setVoice(e.target.value)}>
                    {(voices?.edge ?? []).map((v) => (
                      <option key={v.id} value={v.id}>{v.label}</option>
                    ))}
                    {(voices?.sapi ?? []).map((v) => (
                      <option key={v.id} value={v.id}>{v.label}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            {step === 6 && (
              <div>
                <h1 className="text-xl font-bold text-white">Video style</h1>
                <p className="mt-1 text-sm text-slate-400">Controls the writing tone and caption look.</p>
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  {[
                    ["energetic-explainer", "Energetic explainer"],
                    ["calm-documentary", "Calm documentary"],
                    ["fast-facts", "Fast facts"],
                    ["story-driven", "Story driven"],
                  ].map(([key, label]) => (
                    <button
                      key={key}
                      onClick={() => setStyle(key)}
                      className={cx(
                        "rounded-xl border px-4 py-3 text-left text-sm font-semibold transition-all duration-300 ease-smooth",
                        style === key
                          ? "border-violet-500/50 bg-violet-500/10 text-white"
                          : "border-white/10 text-slate-300 hover:-translate-y-0.5 hover:border-white/20",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {step === 7 && (
              <div>
                <h1 className="text-xl font-bold text-white">Publishing schedule</h1>
                <p className="mt-1 text-sm text-slate-400">You can change this later. Automation starts paused.</p>
                <div className="mt-4 grid gap-4 sm:grid-cols-3">
                  <div>
                    <span className="label">Shorts per day</span>
                    <input type="number" min={1} max={6} className="input" value={videosPerDay} onChange={(e) => setVideosPerDay(Number(e.target.value))} />
                  </div>
                  <div>
                    <span className="label">Publish time</span>
                    <input type="time" className="input" value={publishTime} onChange={(e) => setPublishTime(e.target.value)} />
                  </div>
                  <div>
                    <span className="label">Time zone</span>
                    <input className="input" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
                  </div>
                </div>
              </div>
            )}

            {step === 8 && (
              <div>
                <h1 className="text-xl font-bold text-white">Approval mode</h1>
                <p className="mt-1 text-sm text-slate-400">Recommended: review each video before it goes public.</p>
                <div className="mt-4 space-y-2.5">
                  <button
                    onClick={() => setApprovalMode(true)}
                    className={cx(
                      "w-full rounded-xl border p-4 text-left transition-all duration-300 ease-smooth",
                      approvalMode ? "border-violet-500/50 bg-violet-500/10" : "border-white/10 hover:border-white/20",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-semibold text-white">Approval required (default)</div>
                      <span className={cx("h-2 w-2 rounded-full", approvalMode ? "bg-violet-400" : "bg-slate-600")} />
                    </div>
                    <div className="mt-0.5 text-xs text-slate-400">Videos render, then wait in the queue for your approval before upload.</div>
                  </button>
                  <button
                    onClick={() => setApprovalMode(false)}
                    className={cx(
                      "w-full rounded-xl border p-4 text-left transition-all duration-300 ease-smooth",
                      !approvalMode ? "border-violet-500/50 bg-violet-500/10" : "border-white/10 hover:border-white/20",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-semibold text-white">Fully automatic</div>
                      <span className={cx("h-2 w-2 rounded-full", !approvalMode ? "bg-violet-400" : "bg-slate-600")} />
                    </div>
                    <div className="mt-0.5 text-xs text-slate-400">Anything scoring above your quality threshold uploads on schedule.</div>
                  </button>
                </div>
              </div>
            )}

            {step === 9 && (
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h1 className="text-xl font-bold text-white">Connectivity test</h1>
                  <button onClick={runTests} disabled={busy === "test"} className="btn-primary btn-sm">
                    {busy === "test" ? <Spinner /> : <Icon name="play" className="h-3.5 w-3.5" />}
                    Run tests
                  </button>
                </div>
                <div className="mt-4 space-y-2">
                  {[
                    ["AI model", testResult.ai ?? (check?.ai.models ? `${check.ai.models} model(s) available` : "no model installed"), "chip"],
                    ["Text to speech", testResult.tts ?? (check?.tts?.length ? `chain: ${check.tts.join(" → ")}` : "no engine"), "mic"],
                    ["FFmpeg", testResult.ffmpeg ?? (check?.ffmpeg ? "detected" : "missing"), "film"],
                    ["YouTube", testResult.youtube ?? (check?.channel ? check.channel.title : "not linked"), "upload"],
                  ].map(([label, value, icon]) => (
                    <div key={label} className="flex items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.02] px-3.5 py-2.5">
                      <span className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                        <Icon name={icon as "chip"} className="h-3.5 w-3.5 text-slate-500" />
                        {label}
                      </span>
                      <span className="truncate text-[11px] text-slate-400">{value}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                  A missing AI model is not fatal: script generation falls back to a deterministic template writer. Voice and
                  FFmpeg are required for rendering.
                </p>
              </div>
            )}

            {step === 10 && (
              <div>
                <h1 className="text-xl font-bold text-white">Ready to launch</h1>
                <div className="mt-4 grid gap-2 text-xs sm:grid-cols-2">
                  {[
                    ["Channel", selectedChannel?.title ?? "not linked"],
                    ["Niche", activeNiche?.name ?? "not selected"],
                    ["Language", language],
                    ["Voice", voice],
                    ["Length", `${seconds}s`],
                    ["Style", style],
                    ["Schedule", `${videosPerDay}/day at ${publishTime} ${timezone}`],
                    ["Mode", approvalMode ? "approval required" : "fully automatic"],
                  ].map(([k, v], i) => (
                    <motion.div
                      key={k}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, delay: i * 0.03, ease: [0.16, 1, 0.3, 1] }}
                      className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"
                    >
                      <div className="eyebrow">{k}</div>
                      <div className="mt-0.5 truncate text-slate-200">{v}</div>
                    </motion.div>
                  ))}
                </div>
                <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
                  Automation will remain idle until you press Start on the dashboard. Nothing is uploaded without your
                  configured schedule and approval setting.
                </p>
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        <div className="mt-7 flex items-center justify-between gap-3 border-t border-white/[0.06] pt-5">
          <button onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0} className="btn-ghost">
            <Icon name="chevron" className="h-4 w-4 rotate-180" strokeWidth={2.2} />
            Back
          </button>
          {step < STEPS.length - 1 ? (
            <button onClick={() => setStep((s) => s + 1)} disabled={!canAdvance()} className="btn-primary">
              Continue
              <Icon name="arrowRight" className="h-4 w-4" strokeWidth={2.2} />
            </button>
          ) : (
            <button onClick={finish} disabled={busy === "finish"} className="btn-primary">
              {busy === "finish" ? <Spinner /> : <Icon name="check" className="h-4 w-4" strokeWidth={2.4} />}
              Finish setup
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
