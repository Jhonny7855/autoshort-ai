import { useNavigate, useSearchParams } from "react-router-dom";
import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Icon, type IconName } from "../components/icons";
import { Spinner, cx, AnimatedNumber, OfflineNotice } from "../components/ui";

const STAGES: { name: string; detail: string; icon: IconName }[] = [
  { name: "Niche", detail: "Demand scored against competition", icon: "chart" },
  { name: "Research", detail: "Wikipedia, news RSS, Reddit, YouTube", icon: "search" },
  { name: "Script", detail: "Hook, payoff, scenes, metadata", icon: "doc" },
  { name: "Voice", detail: "Local TTS with word timings", icon: "mic" },
  { name: "Visuals", detail: "Procedural posters, Ken Burns motion", icon: "film" },
  { name: "Render", detail: "FFmpeg 9:16 MP4 with captions", icon: "layers" },
  { name: "Quality", detail: "13 weighted checks, 0–100", icon: "shield" },
  { name: "Publish", detail: "Local package + copy-ready metadata", icon: "upload" },
];

const FEATURES: { title: string; body: string; icon: IconName; accent: string }[] = [
  {
    title: "Local AI writing",
    body: "Ollama models research topics and write hooks, scripts and metadata on your own machine. No API keys, no token bills.",
    icon: "sparkles",
    accent: "from-violet-500/25 to-indigo-500/10 text-violet-300",
  },
  {
    title: "Offline voice + captions",
    body: "Piper or Windows SAPI synthesize narration; captions are burned in word-by-word with seven style presets.",
    icon: "mic",
    accent: "from-cyan-500/25 to-sky-500/10 text-cyan-300",
  },
  {
    title: "FFmpeg render pipeline",
    body: "Scene motion, transitions, music beds and subtitles composited into a 1080×1920 MP4 with resumable presets.",
    icon: "film",
    accent: "from-fuchsia-500/25 to-pink-500/10 text-fuchsia-300",
  },
  {
    title: "Local publishing queue",
    body: "Finished Shorts are packaged with title, description, hashtags and thumbnail — ready to paste into YouTube Studio.",
    icon: "upload",
    accent: "from-emerald-500/25 to-teal-500/10 text-emerald-300",
  },
];

const PROOF: { value: number; suffix?: string; label: string }[] = [
  { value: 0, label: "paid APIs" },
  { value: 13, label: "quality checks" },
  { value: 8, label: "pipeline stages" },
  { value: 100, suffix: "%", label: "on your machine" },
];

export default function Landing() {
  const navigate = useNavigate();
  const { auth, refreshAuth, notify, backendOnline } = useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const reduce = useReducedMotion();
  const heroRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ["start start", "end start"] });
  const heroY = useTransform(scrollYProgress, [0, 1], [0, reduce ? 0 : 60]);
  const heroFade = useTransform(scrollYProgress, [0, 0.8], [1, reduce ? 1 : 0.25]);

  useEffect(() => {
    const err = params.get("auth_error");
    if (!err) return;
    const message =
      err === "access_denied"
        ? "Google sign-in was cancelled. Nothing was connected."
        : `Google sign-in failed (${err}). Try again or continue on this PC.`;
    notify("error", message);
    params.delete("auth_error");
    setParams(params, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const google = () => {
    window.location.href = "/api/auth/google/start?mode=signin";
  };

  const local = async () => {
    setBusy("local");
    try {
      await api.post("/api/auth/local/login");
      await refreshAuth();
      navigate("/onboarding");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Local sign-in failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="relative min-h-screen overflow-x-hidden">
      {/* ambient background */}
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-40 -top-40 h-[560px] w-[560px] animate-aurora rounded-full bg-violet-600/20 blur-[130px]" />
        <div className="absolute -right-32 top-[14%] h-[500px] w-[500px] animate-aurora rounded-full bg-cyan-500/15 blur-[140px] [animation-delay:-7s]" />
        <div className="absolute bottom-[-10%] left-1/3 h-[420px] w-[420px] animate-aurora rounded-full bg-indigo-500/[0.12] blur-[130px] [animation-delay:-14s]" />
        <div className="absolute inset-0 golden-grid noise-mask opacity-[0.55]" />
      </div>

      <header className="relative z-20 mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-3">
          <div className="relative grid h-10 w-10 place-items-center overflow-hidden rounded-xl bg-gradient-to-br from-violet-600 via-indigo-500 to-cyan-500 text-[13px] font-black text-white shadow-glow">
            <span className="relative z-10">AS</span>
            <span className="absolute inset-0 animate-sweep bg-gradient-to-r from-transparent via-white/30 to-transparent" />
          </div>
          <div className="leading-none">
            <div className="text-[13px] font-bold tracking-tight text-white">AUTOSHORT AI</div>
            <div className="mt-1 text-2xs font-medium uppercase tracking-[0.2em] text-slate-500">Autopilot Studio</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="chip hidden border-emerald-500/25 bg-emerald-500/10 text-emerald-300 sm:inline-flex">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Free forever · self-hosted
          </span>
          <button onClick={local} disabled={busy === "local"} className="btn-ghost btn-sm">
            {busy === "local" ? <Spinner /> : "Sign in"}
          </button>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-6xl px-6 pb-28">
        <motion.section ref={heroRef} style={{ y: heroY, opacity: heroFade }} className="grid items-center gap-14 pt-8 lg:grid-cols-[1.06fr_0.94fr]">
          <div>
            <motion.div
              initial={reduce ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
              className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11px] font-semibold text-slate-300 backdrop-blur"
            >
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-pulseRing rounded-full bg-emerald-400/70" />
                <span className="relative h-1.5 w-1.5 rounded-full bg-emerald-400" />
              </span>
              Zero paid APIs · Local models · Your hardware
            </motion.div>

            <h1 className="text-[42px] font-extrabold leading-[1.03] tracking-[-0.03em] text-white sm:text-[56px] lg:text-[64px]">
              {"Your YouTube Channel.".split(" ").map((word, i) => (
                <motion.span
                  key={i}
                  initial={reduce ? false : { opacity: 0, y: 22, filter: "blur(8px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  transition={{ duration: 0.7, delay: 0.05 + i * 0.07, ease: [0.16, 1, 0.3, 1] }}
                  className="inline-block"
                >
                  {word}&nbsp;
                </motion.span>
              ))}
              <br />
              <motion.span
                initial={reduce ? false : { opacity: 0, y: 22, filter: "blur(10px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                transition={{ duration: 0.8, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
                className="grad-text inline-block"
              >
                On Autopilot.
              </motion.span>
            </h1>

            <motion.p
              initial={reduce ? false : { opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.42 }}
              className="mt-6 max-w-xl text-[15px] leading-relaxed text-slate-400"
            >
              AUTOSHORT AI researches topics, writes scripts, generates narration and visuals, renders vertical Shorts
              with burned-in captions — and packages each one for publishing on a schedule you set.
            </motion.p>

            {backendOnline === false && (
              <motion.div
                initial={reduce ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.5 }}
                className="mt-5 max-w-xl"
              >
                <OfflineNotice />
              </motion.div>
            )}

            <motion.div
              initial={reduce ? false : { opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.52 }}
              className="mt-9 flex flex-wrap items-center gap-3"
            >
              <button
                onClick={() => {
                  if (backendOnline === false) {
                    notify("error", "The local backend is not running. Clone the repo and run start.bat.");
                    return;
                  }
                  void local();
                }}
                disabled={busy === "local"}
                className="btn-primary group h-12 px-6 text-[15px]"
              >
                {busy === "local" ? <Spinner /> : "Continue on this PC"}
                {busy !== "local" && (
                  <Icon name="arrowRight" className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" strokeWidth={2} />
                )}
              </button>
              {auth?.google_configured ? (
                <button onClick={google} className="btn-ghost h-12 px-5 text-[15px]">
                  <svg viewBox="0 0 24 24" className="h-5 w-5">
                    <path
                      fill="currentColor"
                      d="M21.35 11.1H12v2.98h5.35c-.25 1.5-1.75 4.4-5.35 4.4a5.9 5.9 0 010-11.8c1.7 0 2.85.72 3.5 1.34l2.4-2.31C16.35 4.17 14.4 3.3 12 3.3a9.2 9.2 0 100 18.4c5.3 0 8.8-3.73 8.8-8.98 0-.6-.07-1.06-.15-1.62z"
                    />
                  </svg>
                  Sign in with Google
                </button>
              ) : null}
            </motion.div>

            <motion.p
              initial={reduce ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.6, delay: 0.7 }}
              className="mt-5 max-w-lg text-[12px] leading-relaxed text-slate-500"
            >
              Everything runs on this machine: local AI writes the script, local TTS narrates, FFmpeg renders. No Google
              Cloud project, no API keys, no subscriptions.
            </motion.p>

            <motion.dl
              initial={reduce ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.6, delay: 0.8 }}
              className="mt-9 grid max-w-lg grid-cols-2 gap-x-8 gap-y-4 border-t border-white/[0.06] pt-6 sm:grid-cols-4"
            >
              {PROOF.map((p) => (
                <div key={p.label}>
                  <dt className="numeric text-xl font-bold text-white">
                    <AnimatedNumber value={p.value} />
                    {p.suffix}
                  </dt>
                  <dd className="mt-0.5 text-2xs uppercase tracking-[0.14em] text-slate-500">{p.label}</dd>
                </div>
              ))}
            </motion.dl>
          </div>

          <motion.div
            initial={reduce ? false : { opacity: 0, scale: 0.96, y: 18 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="card-lit relative p-6"
          >
            <div className="relative">
              <div className="mb-5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="eyebrow">Pipeline</span>
                  <span className="chip border-violet-500/25 bg-violet-500/10 text-violet-300">8 stages</span>
                </div>
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="h-1.5 w-1.5 animate-breathe rounded-full bg-slate-600"
                      style={{ animationDelay: `${i * 0.35}s` }}
                    />
                  ))}
                </div>
              </div>

              <ol className="relative space-y-1">
                <span className="absolute bottom-3 left-[15px] top-3 w-px bg-gradient-to-b from-violet-500/40 via-white/10 to-transparent" />
                {STAGES.map((stage, i) => (
                  <motion.li
                    key={stage.name}
                    initial={reduce ? false : { opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.45, delay: 0.45 + i * 0.07, ease: [0.16, 1, 0.3, 1] }}
                    className="group relative flex items-center gap-3 rounded-xl px-1.5 py-2 transition-colors hover:bg-white/[0.03]"
                  >
                    <span className="relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/[0.08] bg-ink-850 text-slate-500 transition-colors duration-300 group-hover:border-violet-500/40 group-hover:text-violet-300">
                      <Icon name={stage.icon} className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12.5px] font-semibold text-slate-200">{stage.name}</div>
                      <div className="truncate text-[11px] text-slate-500">{stage.detail}</div>
                    </div>
                    <span className="numeric text-2xs text-slate-700">{String(i + 1).padStart(2, "0")}</span>
                  </motion.li>
                ))}
              </ol>

              <div className="mt-5 overflow-hidden rounded-xl border border-white/[0.06] bg-ink-950/70 p-3 font-mono text-[11px] leading-relaxed">
                <div className="flex items-center gap-1.5 pb-2">
                  <span className="h-2 w-2 rounded-full bg-rose-500/60" />
                  <span className="h-2 w-2 rounded-full bg-amber-500/60" />
                  <span className="h-2 w-2 rounded-full bg-emerald-500/60" />
                  <span className="ml-1.5 text-2xs text-slate-600">autoshort · local</span>
                </div>
                <div className="text-slate-500">
                  <span className="text-emerald-400">$</span> autoshort run --offline
                </div>
                <div className="text-slate-600">
                  → 0 API keys required · <span className="text-cyan-400/80">ready</span>
                  <span className="ml-1 inline-block h-3 w-1.5 translate-y-0.5 animate-breathe bg-violet-400/80" />
                </div>
              </div>
            </div>
          </motion.div>
        </motion.section>

        <section className="mt-24">
          <motion.div
            initial={reduce ? false : { opacity: 0, y: 14 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.6 }}
            className="mb-8 flex flex-wrap items-end justify-between gap-3"
          >
            <div>
              <div className="eyebrow mb-2">Built for solo creators</div>
              <h2 className="max-w-xl text-[28px] font-bold leading-tight tracking-[-0.02em] text-white">
                A full production studio that costs nothing to run.
              </h2>
            </div>
            <p className="max-w-sm text-[13px] leading-relaxed text-slate-500">
              Four systems, one local app. Nothing phones home, nothing bills you per token.
            </p>
          </motion.div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f, i) => (
              <motion.article
                key={f.title}
                initial={reduce ? false : { opacity: 0, y: 18 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.55, delay: i * 0.07, ease: [0.16, 1, 0.3, 1] }}
                className="card card-hover group relative overflow-hidden p-5"
              >
                <div className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-violet-500/[0.07] blur-2xl transition-opacity duration-500 group-hover:opacity-100" />
                <div
                  className={cx(
                    "mb-4 grid h-10 w-10 place-items-center rounded-xl border border-white/[0.07] bg-gradient-to-br transition-transform duration-400 ease-smooth group-hover:-translate-y-0.5 group-hover:scale-105",
                    f.accent,
                  )}
                >
                  <Icon name={f.icon} className="h-[18px] w-[18px]" />
                </div>
                <h3 className="text-[13.5px] font-semibold text-white">{f.title}</h3>
                <p className="mt-2 text-[12px] leading-relaxed text-slate-400">{f.body}</p>
              </motion.article>
            ))}
          </div>
        </section>

        <motion.section
          initial={reduce ? false : { opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="mt-20 overflow-hidden rounded-3xl border border-white/[0.07] bg-white/[0.02]"
        >
          <div className="grid divide-y divide-white/[0.06] md:grid-cols-3 md:divide-x md:divide-y-0">
            {[
              {
                title: "Privacy",
                icon: "shield" as IconName,
                body: "Everything runs on this computer. Tokens are encrypted at rest with a key stored locally in your data folder. AUTOSHORT AI never asks for your Google password and never scrapes sessions.",
              },
              {
                title: "Compliance",
                icon: "check" as IconName,
                body: "Private-by-default uploads, duplicate detection, an originality fingerprint per topic, and a review queue so the channel does not publish repetitive AI spam.",
              },
              {
                title: "Cost",
                icon: "chart" as IconName,
                body: "No paid AI, voice, rendering or hosting. Optional: an internet connection for free Edge TTS and Google News RSS. Local models and SAPI voice work fully offline.",
              },
            ].map((block) => (
              <div key={block.title} className="p-6">
                <div className="mb-3 flex items-center gap-2 text-slate-300">
                  <Icon name={block.icon} className="h-4 w-4 text-violet-300" />
                  <h4 className="text-2xs font-bold uppercase tracking-[0.16em] text-slate-400">{block.title}</h4>
                </div>
                <p className="text-[12px] leading-relaxed text-slate-400">{block.body}</p>
              </div>
            ))}
          </div>
        </motion.section>

        <motion.section
          initial={reduce ? false : { opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7 }}
          className="relative mt-16 overflow-hidden rounded-3xl border border-white/[0.08] p-8 text-center sm:p-12"
        >
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-violet-600/[0.12] via-transparent to-cyan-500/10" />
          <motion.div
            aria-hidden
            className="pointer-events-none absolute left-1/2 top-0 h-56 w-56 -translate-x-1/2 rounded-full bg-violet-500/[0.16] blur-[90px]"
            animate={reduce ? undefined : { scale: [1, 1.18, 1], opacity: [0.6, 1, 0.6] }}
            transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
          />
          <div className="relative">
            <h2 className="mx-auto max-w-lg text-[26px] font-bold leading-tight tracking-[-0.02em] text-white">
              Start with your first Short in a few minutes.
            </h2>
            <p className="mx-auto mt-3 max-w-md text-[13px] leading-relaxed text-slate-400">
              No account, no card, no cloud project. Sign in locally and the wizard checks your hardware for you.
            </p>
            <button onClick={local} disabled={busy === "local"} className="btn-primary group mt-7 h-12 px-7 text-[15px]">
              {busy === "local" ? <Spinner /> : "Open the studio"}
              {busy !== "local" && (
                <Icon name="arrowRight" className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" strokeWidth={2} />
              )}
            </button>
          </div>
        </motion.section>
      </main>

      <footer className="relative z-10 border-t border-white/[0.06] py-6">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-6 text-[11px] text-slate-600">
          <span>AUTOSHORT AI · self-hosted autopilot studio</span>
          <span>Local models · local voice · local render</span>
        </div>
      </footer>
    </div>
  );
}
