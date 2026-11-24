import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion, useScroll, useSpring } from "framer-motion";
import { useApp } from "../lib/store";
import { cx } from "./ui";
import { Icon, type IconName } from "./icons";
import Ambient from "./Ambient";

type NavItem = { to: string; label: string; icon: IconName; group: string };

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Overview", icon: "home", group: "Studio" },
  { to: "/automation", label: "Automation", icon: "bolt", group: "Studio" },
  { to: "/ideas", label: "Content Ideas", icon: "bulb", group: "Studio" },
  { to: "/scripts", label: "Script Studio", icon: "doc", group: "Studio" },
  { to: "/video", label: "Video Studio", icon: "film", group: "Studio" },
  { to: "/queue", label: "Queue", icon: "layers", group: "Studio" },
  { to: "/calendar", label: "Content Calendar", icon: "calendar", group: "Publish" },
  { to: "/publishing", label: "Publishing", icon: "upload", group: "Publish" },
  { to: "/published", label: "Published", icon: "bookmark", group: "Publish" },
  { to: "/analytics", label: "Analytics", icon: "chart", group: "Publish" },
  { to: "/ai", label: "AI Engine", icon: "chip", group: "Configuration" },
  { to: "/voice", label: "Voice", icon: "mic", group: "Configuration" },
  { to: "/settings", label: "Settings", icon: "gear", group: "Configuration" },
  { to: "/resources", label: "Resources", icon: "server", group: "Configuration" },
  { to: "/logs", label: "Logs", icon: "list", group: "Configuration" },
];

function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative grid h-9 w-9 place-items-center overflow-hidden rounded-xl bg-gradient-to-br from-violet-600 via-indigo-500 to-cyan-500 text-[13px] font-black text-white shadow-glow">
        <span className="relative z-10">AS</span>
        <span className="absolute inset-0 animate-sweep bg-gradient-to-r from-transparent via-white/35 to-transparent" />
      </div>
      {!compact && (
        <div className="leading-none">
          <div className="text-[13px] font-bold tracking-tight text-white">AUTOSHORT AI</div>
          <div className="mt-1 text-2xs font-medium uppercase tracking-[0.18em] text-slate-500">Autopilot Studio</div>
        </div>
      )}
    </div>
  );
}

export default function Shell() {
  const { auth, logout, toasts, dismiss, wsConnected } = useApp();
  const nav = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, { stiffness: 140, damping: 28, restDelta: 0.001 });

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (auth && !auth.authenticated) nav("/");
  }, [auth, nav]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const groups = useMemo(() => {
    const map = new Map<string, NavItem[]>();
    NAV.forEach((item) => {
      const list = map.get(item.group) ?? [];
      list.push(item);
      map.set(item.group, list);
    });
    return [...map.entries()];
  }, []);

  const current = NAV.find((n) => location.pathname.startsWith(n.to));
  const initials = (auth?.user?.name || auth?.user?.email || "AS")
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  const sidebar = (
    <>
      <div className="flex h-16 items-center px-5">
        <Brand />
      </div>

      <nav className="scrollbar-thin min-h-0 flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {groups.map(([group, items]) => (
          <div key={group}>
            <div className="mb-1.5 flex items-center gap-2 px-3">
              <span className="eyebrow text-[9.5px] text-slate-600">{group}</span>
              <span className="h-px flex-1 bg-gradient-to-r from-white/[0.07] to-transparent" />
            </div>
            <div className="space-y-0.5">
              {items.map((item) => {
                const active = location.pathname.startsWith(item.to);
                return (
                  <NavLink key={item.to} to={item.to} className={cx("sidebar-link group", active && "sidebar-link-active")}>
                    {active && (
                      <motion.span
                        layoutId="nav-active"
                        className="absolute inset-0 rounded-xl bg-white/[0.06]"
                        transition={{ type: "spring", stiffness: 420, damping: 34 }}
                      />
                    )}
                    <span className={cx("relative transition-colors", active ? "text-violet-300" : "text-slate-500 group-hover:text-slate-300")}>
                      <Icon name={item.icon} className="h-[17px] w-[17px]" />
                    </span>
                    <span className="relative flex-1 truncate">{item.label}</span>
                    {active && (
                      <motion.span
                        initial={{ scale: 0 }}
                        animate={{ scale: 1 }}
                        className="relative h-1 w-1 rounded-full bg-violet-400 shadow-[0_0_8px_2px_rgba(167,139,250,0.5)]"
                      />
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-white/[0.06] p-3">
        <div className="group flex items-center gap-2.5 rounded-xl border border-white/[0.06] bg-white/[0.025] p-2.5 transition-colors hover:border-white/10 hover:bg-white/[0.045]">
          {auth?.user?.picture ? (
            <img src={auth.user.picture} alt="" className="h-8 w-8 rounded-lg object-cover ring-1 ring-white/10" />
          ) : (
            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-white/[0.12] to-white/5 text-[11px] font-bold text-slate-200 ring-1 ring-white/10">
              {initials}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12px] font-semibold text-slate-200">{auth?.user?.name ?? "Local user"}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-500">
              <span className="relative flex h-1.5 w-1.5">
                {wsConnected && <span className="absolute inline-flex h-full w-full animate-pulseRing rounded-full bg-emerald-400/70" />}
                <span className={cx("relative h-1.5 w-1.5 rounded-full", wsConnected ? "bg-emerald-400" : "bg-slate-600")} />
              </span>
              {wsConnected ? "live" : "offline"}
            </div>
          </div>
          <button
            onClick={logout}
            className="rounded-lg p-1.5 text-slate-500 opacity-0 transition-all duration-200 hover:bg-white/10 hover:text-rose-300 group-hover:opacity-100 focus-visible:opacity-100"
            title="Sign out"
            aria-label="Sign out"
          >
            <Icon name="logout" className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div className="relative flex min-h-screen">
      <Ambient />

      <aside className="sticky top-0 z-20 hidden h-screen w-[244px] shrink-0 flex-col border-r border-white/[0.06] bg-ink-900/70 backdrop-blur-xl lg:flex">
        {sidebar}
      </aside>

      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              key="scrim"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
              className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
            />
            <motion.aside
              key="drawer"
              initial={{ x: -260 }}
              animate={{ x: 0 }}
              exit={{ x: -260 }}
              transition={{ type: "spring", stiffness: 380, damping: 36 }}
              className="fixed inset-y-0 left-0 z-50 flex w-[268px] flex-col border-r border-white/[0.08] bg-ink-900/[0.98] backdrop-blur-xl lg:hidden"
            >
              <button
                onClick={() => setMobileOpen(false)}
                className="absolute right-3 top-4 rounded-lg p-1.5 text-slate-500 hover:bg-white/10 hover:text-white"
                aria-label="Close navigation"
              >
                <Icon name="close" className="h-4 w-4" />
              </button>
              {sidebar}
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-white/[0.06] bg-ink-950/75 px-4 backdrop-blur-xl lg:px-8">
          <motion.div
            aria-hidden
            style={{ scaleX: progress }}
            className="absolute inset-x-0 bottom-0 h-[2px] origin-left bg-gradient-to-r from-violet-500 via-indigo-400 to-cyan-400"
          />
          <button
            className="rounded-lg border border-white/10 p-2 text-slate-300 transition hover:border-white/20 hover:text-white lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Icon name="menu" className="h-5 w-5" strokeWidth={1.8} />
          </button>

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 text-2xs font-medium text-slate-600">
              <span className="hidden sm:inline">Studio</span>
              <Icon name="chevron" className="hidden h-2.5 w-2.5 sm:inline" strokeWidth={2.4} />
              <AnimatePresence mode="wait" initial={false}>
                <motion.span
                  key={current?.label ?? "Overview"}
                  initial={reduce ? false : { opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduce ? undefined : { opacity: 0, y: 4 }}
                  transition={{ duration: 0.16 }}
                  className="text-slate-400"
                >
                  {current?.label ?? "Overview"}
                </motion.span>
              </AnimatePresence>
            </div>
            <div className="truncate text-[13px] font-semibold text-white">
              {auth?.channel ? auth.channel.title : "Local workspace"}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span
              className={cx(
                "chip hidden sm:inline-flex",
                wsConnected ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" : "border-white/10 bg-white/5 text-slate-400",
              )}
            >
              <span className={cx("h-1.5 w-1.5 rounded-full", wsConnected ? "animate-breathe bg-emerald-400" : "bg-slate-500")} />
              {wsConnected ? "Live" : "Offline"}
            </span>
            {auth?.channel?.thumbnail ? (
              <img src={auth.channel.thumbnail} alt="" className="h-8 w-8 rounded-full ring-2 ring-white/10" />
            ) : (
              <span className="chip border-violet-500/25 bg-violet-500/10 text-violet-300">Local mode</span>
            )}
          </div>
        </header>

        <main className="relative min-h-0 flex-1 px-4 py-6 lg:px-8 lg:py-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={reduce ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduce ? undefined : { opacity: 0, y: -6 }}
              transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
              className="mx-auto w-full max-w-[1400px]"
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(340px,calc(100vw-2rem))] flex-col gap-2">
        <AnimatePresence initial={false}>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, x: 40, scale: 0.97 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 40, scale: 0.97 }}
              transition={{ type: "spring", stiffness: 420, damping: 34 }}
              className={cx(
                "pointer-events-auto flex items-start gap-2.5 overflow-hidden rounded-xl border p-3 text-xs shadow-lift backdrop-blur-md",
                toast.kind === "success" && "border-emerald-500/25 bg-emerald-500/[0.12] text-emerald-100",
                toast.kind === "error" && "border-rose-500/25 bg-rose-500/[0.12] text-rose-100",
                toast.kind === "info" && "border-white/10 bg-ink-800/95 text-slate-200",
              )}
            >
              <span
                className={cx(
                  "mt-0.5 shrink-0",
                  toast.kind === "success" ? "text-emerald-400" : toast.kind === "error" ? "text-rose-400" : "text-slate-400",
                )}
              >
                <Icon
                  name={toast.kind === "success" ? "check" : toast.kind === "error" ? "alert" : "sparkles"}
                  className="h-4 w-4"
                  strokeWidth={2}
                />
              </span>
              <span className="flex-1 leading-relaxed">{toast.message}</span>
              <button onClick={() => dismiss(toast.id)} className="shrink-0 text-current opacity-40 transition hover:opacity-100" aria-label="Dismiss">
                <Icon name="close" className="h-3.5 w-3.5" strokeWidth={2.2} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
