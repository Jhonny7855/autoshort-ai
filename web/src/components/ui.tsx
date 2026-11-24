import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion";
import { Icon, type IconName } from "./icons";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

const STATUS_TONE: Record<string, string> = {
  IDEA: "border-slate-500/25 bg-slate-500/10 text-slate-300",
  RESEARCHING: "border-sky-500/25 bg-sky-500/10 text-sky-300",
  SCRIPT_READY: "border-indigo-500/25 bg-indigo-500/10 text-indigo-300",
  WAITING_FOR_APPROVAL: "border-amber-500/25 bg-amber-500/10 text-amber-300",
  NEEDS_REVIEW: "border-amber-500/25 bg-amber-500/10 text-amber-300",
  GENERATING_AUDIO: "border-cyan-500/25 bg-cyan-500/10 text-cyan-300",
  GENERATING_VISUALS: "border-teal-500/25 bg-teal-500/10 text-teal-300",
  RENDERING: "border-violet-500/25 bg-violet-500/10 text-violet-300",
  QUALITY_CHECK: "border-fuchsia-500/25 bg-fuchsia-500/10 text-fuchsia-300",
  READY_TO_UPLOAD: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
  READY: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
  UPLOADING: "border-blue-500/25 bg-blue-500/10 text-blue-300",
  SCHEDULED: "border-purple-500/25 bg-purple-500/10 text-purple-300",
  PENDING_REVIEW: "border-amber-500/25 bg-amber-500/10 text-amber-300",
  PUBLISHED: "border-green-500/25 bg-green-500/10 text-green-300",
  FAILED: "border-rose-500/25 bg-rose-500/10 text-rose-300",
  CANCELLED: "border-zinc-500/25 bg-zinc-500/10 text-zinc-400",
  DONE: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
};

const STATUS_DOT: Record<string, string> = {
  FAILED: "bg-rose-400",
  CANCELLED: "bg-zinc-500",
  PUBLISHED: "bg-green-400",
  READY_TO_UPLOAD: "bg-emerald-400",
  READY: "bg-emerald-400",
  RENDERING: "bg-violet-400",
  GENERATING_AUDIO: "bg-cyan-400",
  GENERATING_VISUALS: "bg-teal-400",
  QUALITY_CHECK: "bg-fuchsia-400",
  WAITING_FOR_APPROVAL: "bg-amber-400",
  NEEDS_REVIEW: "bg-amber-400",
  PENDING_REVIEW: "bg-amber-400",
  SCHEDULED: "bg-purple-400",
  UPLOADING: "bg-blue-400",
};

export function StatusChip({ status }: { status: string }) {
  const key = status.replaceAll(" ", "_").toUpperCase();
  const tone = STATUS_TONE[key] ?? "border-white/10 bg-white/5 text-slate-300";
  return (
    <span className={cx("chip", tone)}>
      <span className={cx("h-1 w-1 rounded-full", STATUS_DOT[key] ?? "bg-slate-500")} />
      {status.replaceAll("_", " ").toLowerCase()}
    </span>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("card p-5", className)}>{children}</div>;
}

export function SectionTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold tracking-tight text-white">{title}</h2>
        {subtitle && <p className="mt-1 text-[12.5px] leading-relaxed text-slate-500">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Layout: page headers
 * ------------------------------------------------------------------ */

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  children,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="relative">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
          <h1 className="text-[26px] font-bold leading-tight tracking-[-0.02em] text-white sm:text-[28px]">{title}</h1>
          {subtitle && <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-slate-400">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  );
}

/* ------------------------------------------------------------------ *
 * Motion helpers
 * ------------------------------------------------------------------ */

/** Pointer-following highlight. Purely decorative, disabled for reduced motion. */
export function Spotlight({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const [spot, setSpot] = useState<{ x: number; y: number; on: boolean }>({ x: 50, y: 0, on: false });

  return (
    <div
      ref={ref}
      onPointerMove={(e) => {
        if (reduce) return;
        const box = ref.current?.getBoundingClientRect();
        if (!box) return;
        setSpot({
          x: ((e.clientX - box.left) / box.width) * 100,
          y: ((e.clientY - box.top) / box.height) * 100,
          on: true,
        });
      }}
      onPointerLeave={() => setSpot((prev) => ({ ...prev, on: false }))}
      className={cx("relative", className)}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-[inherit] transition-opacity duration-500"
        style={{
          opacity: spot.on ? 1 : 0,
          background: `radial-gradient(260px circle at ${spot.x}% ${spot.y}%, rgba(167,139,250,0.13), rgba(34,211,238,0.05) 42%, transparent 68%)`,
        }}
      />
      {children}
    </div>
  );
}

/** Counts up to a value instead of snapping. Strings fall through untouched. */
export function AnimatedNumber({ value, className }: { value: number; className?: string }) {
  const reduce = useReducedMotion();
  const target = Number.isFinite(value) ? value : 0;
  const mv = useMotionValue(reduce ? target : 0);
  const spring = useSpring(mv, { stiffness: 120, damping: 24, mass: 0.7 });
  const text = useTransform(spring, (v) => String(Math.round(v)));

  useEffect(() => {
    if (reduce) {
      mv.set(target);
      return;
    }
    mv.set(target);
  }, [mv, reduce, target]);

  if (reduce) return <span className={className}>{Math.round(target)}</span>;
  return <motion.span className={className}>{text}</motion.span>;
}

export function Reveal({
  children,
  delay = 0,
  y = 10,
  className,
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.16, 1, 0.3, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function Stagger({ children, className, step = 0.05 }: { children: ReactNode; className?: string; step?: number }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="show"
      variants={{
        hidden: {},
        show: { transition: { staggerChildren: reduce ? 0 : step } },
      }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      variants={{
        hidden: reduce ? {} : { opacity: 0, y: 12 },
        show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] } },
      }}
    >
      {children}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ *
 * Metric cards
 * ------------------------------------------------------------------ */

const ACCENTS: Record<string, { text: string; glow: string; bar: string }> = {
  emerald: { text: "text-emerald-300", glow: "rgba(52,211,153,0.20)", bar: "from-emerald-400/70" },
  amber: { text: "text-amber-300", glow: "rgba(251,191,36,0.18)", bar: "from-amber-400/70" },
  violet: { text: "text-violet-300", glow: "rgba(167,139,250,0.22)", bar: "from-violet-400/70" },
  cyan: { text: "text-cyan-300", glow: "rgba(34,211,238,0.18)", bar: "from-cyan-400/70" },
  rose: { text: "text-rose-300", glow: "rgba(251,113,133,0.18)", bar: "from-rose-400/70" },
  slate: { text: "text-slate-200", glow: "rgba(148,163,184,0.14)", bar: "from-slate-400/60" },
};

export function StatCard({
  label,
  value,
  hint,
  accent = "slate",
  icon,
  loading,
  footer,
}: {
  label: string;
  value: string | number;
  hint?: string;
  accent?: keyof typeof ACCENTS;
  icon?: IconName;
  loading?: boolean;
  footer?: ReactNode;
}) {
  const tone = ACCENTS[accent] ?? ACCENTS.slate;
  return (
    <Spotlight className="h-full">
      <div className="stat-card group h-full">
        <div
          className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
          style={{ background: `radial-gradient(120% 100% at 100% 0%, ${tone.glow}, transparent 62%)` }}
        />
        <div className="relative flex items-start justify-between gap-2">
          <div className="eyebrow">{label}</div>
          {icon && (
            <span className={cx("rounded-lg bg-white/[0.05] p-1.5 transition-transform duration-300 ease-smooth group-hover:scale-110", tone.text)}>
              <Icon name={icon} className="h-3.5 w-3.5" />
            </span>
          )}
        </div>
        <div className="relative mt-2">
          {loading ? (
            <Skeleton className="h-7 w-14" />
          ) : typeof value === "number" ? (
            <AnimatedNumber value={value} className={cx("numeric block text-[26px] font-bold leading-none", tone.text)} />
          ) : (
            <div className={cx("numeric text-[26px] font-bold leading-none", tone.text)}>{value}</div>
          )}
        </div>
        {hint && <div className="relative mt-1.5 text-[11px] leading-snug text-slate-500">{hint}</div>}
        {footer && <div className="relative mt-3">{footer}</div>}
      </div>
    </Spotlight>
  );
}

/* ------------------------------------------------------------------ *
 * Data display
 * ------------------------------------------------------------------ */

export function Progress({ value, className, tone }: { value: number; className?: string; tone?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={cx("relative h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]", className)}>
      <motion.div
        className="h-full rounded-full"
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        style={{
          backgroundImage: tone ?? "linear-gradient(90deg,#7c3aed,#6366f1,#22d3ee)",
          boxShadow: "0 0 12px rgba(139,92,246,0.45)",
        }}
      />
    </div>
  );
}

export function ScoreRing({ score, size = 74, label }: { score: number; size?: number; label?: string }) {
  const radius = (size - 10) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, score));
  const color = score >= 85 ? "#34d399" : score >= 75 ? "#22d3ee" : score >= 60 ? "#fbbf24" : "#fb7185";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} stroke="rgba(255,255,255,0.07)" strokeWidth={7} fill="none" />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={color}
          strokeWidth={7}
          fill="none"
          strokeDasharray={circumference}
          strokeLinecap="round"
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - clamped / 100) }}
          transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
          style={{ filter: `drop-shadow(0 0 6px ${color}66)` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center leading-none">
          <div className="numeric font-bold text-white" style={{ fontSize: size * 0.26 }}>
            {Math.round(score)}
          </div>
          {label && <div className="mt-0.5 text-2xs uppercase tracking-wider text-slate-500">{label}</div>}
        </div>
      </div>
    </div>
  );
}

export function Empty({
  title,
  body,
  action,
  icon = "sparkles",
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  icon?: IconName;
}) {
  return (
    <div className="relative flex flex-col items-center justify-center gap-3 overflow-hidden rounded-2xl border border-dashed border-white/[0.08] px-6 py-14 text-center">
      <div className="pointer-events-none absolute -top-16 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-violet-600/10 blur-3xl" />
      <motion.span
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="grid h-11 w-11 place-items-center rounded-2xl border border-white/[0.08] bg-white/[0.04] text-violet-300"
      >
        <Icon name={icon} className="h-5 w-5" />
      </motion.span>
      <div className="text-[15px] font-semibold text-slate-200">{title}</div>
      {body && <p className="max-w-sm text-[12.5px] leading-relaxed text-slate-500">{body}</p>}
      {action && <div className="pt-1">{action}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cx(
        "inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/15 border-t-violet-400",
        className,
      )}
      role="status"
      aria-label="Loading"
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton h-4 w-full", className)} />;
}

export function Divider({ className }: { className?: string }) {
  return <div className={cx("divider", className)} />;
}

/**
 * Shown when the app is served as a static UI preview with no FastAPI backend
 * behind it. States the truth instead of letting every action fail silently.
 */
export function OfflineNotice({ className }: { className?: string }) {
  return (
    <div
      className={cx(
        "flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.07] p-3.5 text-[11.5px] leading-relaxed text-amber-200/85",
        className,
      )}
    >
      <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
      <div>
        <div className="font-semibold text-amber-100">Interface preview — backend not connected</div>
        <div className="mt-1">
          This page is the static React interface. The generator needs the local FastAPI server, FFmpeg, TTS and Ollama,
          which cannot run in a browser. Clone the repo and run <span className="font-mono text-amber-200">start.bat</span> to
          use it for real.
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Tabs
 * ------------------------------------------------------------------ */

export function Tabs({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: { key: string; label: string; count?: number }[];
  value: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div className={cx("scrollbar-none -mx-1 flex gap-1 overflow-x-auto px-1", className)} role="tablist">
      {tabs.map((tab) => {
        const active = tab.key === value;
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.key)}
            className={cx(
              "relative shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors duration-200",
              active ? "text-white" : "text-slate-500 hover:text-slate-300",
            )}
          >
            {active && (
              <motion.span
                layoutId="tab-pill"
                className="absolute inset-0 rounded-lg border border-violet-400/30 bg-violet-500/15"
                transition={{ type: "spring", stiffness: 380, damping: 32 }}
              />
            )}
            <span className="relative flex items-center gap-1.5">
              {tab.label}
              {tab.count !== undefined && (
                <span className={cx("numeric text-2xs", active ? "text-violet-200/80" : "text-slate-600")}>{tab.count}</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Formatting
 * ------------------------------------------------------------------ */

export function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const abs = Math.abs(diff);
  const suffix = diff >= 0 ? "ago" : "from now";
  const mins = Math.round(abs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ${suffix}`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ${suffix}`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ${suffix}`;
  return new Date(iso).toLocaleDateString();
}

export function fmtNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
