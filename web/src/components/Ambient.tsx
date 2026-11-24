import { motion, useReducedMotion } from "framer-motion";

/**
 * Ambient ambience layer: slow drifting colour fields behind every screen.
 * Purely decorative, pointer-transparent, and disabled for reduced motion.
 */
export default function Ambient() {
  const reduce = useReducedMotion();
  const drift = (delay: number, duration: number) =>
    reduce
      ? {}
      : {
          animate: {
            x: [0, 28, -18, 0],
            y: [0, -24, 16, 0],
            scale: [1, 1.08, 0.96, 1],
          },
          transition: { duration, delay, repeat: Infinity, ease: "easeInOut" as const },
        };

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      <motion.div
        {...drift(0, 26)}
        className="absolute -left-48 -top-56 h-[560px] w-[560px] rounded-full bg-violet-600/[0.16] blur-[130px]"
      />
      <motion.div
        {...drift(4, 31)}
        className="absolute -right-52 top-[-8rem] h-[520px] w-[520px] rounded-full bg-cyan-500/[0.11] blur-[130px]"
      />
      <motion.div
        {...drift(8, 36)}
        className="absolute bottom-[-18rem] left-1/3 h-[520px] w-[620px] rounded-full bg-indigo-500/[0.10] blur-[140px]"
      />
      <div className="absolute inset-0 golden-grid noise-mask opacity-[0.5]" />
      <div className="absolute inset-0 bg-[radial-gradient(120%_90%_at_50%_-10%,transparent_35%,rgba(5,6,10,0.55)_100%)]" />
    </div>
  );
}
