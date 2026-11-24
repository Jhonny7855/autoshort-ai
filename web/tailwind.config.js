/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#05060a",
          900: "#080a11",
          850: "#0b0e16",
          800: "#0f131d",
          750: "#141926",
          700: "#1a2032",
          600: "#252c40",
          500: "#343d55",
        },
        violet: {
          300: "#c4b5fd",
          400: "#a78bfa",
          500: "#8b5cf6",
          600: "#7c3aed",
          700: "#6d28d9",
        },
        cyan: {
          300: "#67e8f9",
          400: "#22d3ee",
          500: "#06b6d4",
        },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["10px", { lineHeight: "14px" }],
      },
      borderRadius: {
        "3xl": "22px",
        "4xl": "28px",
      },
      boxShadow: {
        glow: "0 0 40px rgba(124, 58, 237, 0.28)",
        card: "0 18px 48px -24px rgba(0, 0, 0, 0.85)",
        lift: "0 30px 64px -32px rgba(0, 0, 0, 0.95), 0 0 0 1px rgba(255, 255, 255, 0.05)",
        "inset-line": "inset 0 1px 0 0 rgba(255, 255, 255, 0.06)",
      },
      transitionTimingFunction: {
        smooth: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      transitionDuration: {
        400: "400ms",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-800px 0" },
          "100%": { backgroundPosition: "800px 0" },
        },
        floaty: {
          "0%,100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        pulseRing: {
          "0%": { transform: "scale(0.9)", opacity: "0.7" },
          "70%": { transform: "scale(1.9)", opacity: "0" },
          "100%": { opacity: "0" },
        },
        aurora: {
          "0%,100%": { transform: "translate3d(0,0,0) scale(1)" },
          "33%": { transform: "translate3d(4%, -6%, 0) scale(1.09)" },
          "66%": { transform: "translate3d(-5%, 4%, 0) scale(0.95)" },
        },
        sweep: {
          "0%": { transform: "translateX(-120%)" },
          "100%": { transform: "translateX(220%)" },
        },
        marquee: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        gradientShift: {
          "0%,100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        breathe: {
          "0%,100%": { opacity: "0.45" },
          "50%": { opacity: "0.9" },
        },
      },
      animation: {
        shimmer: "shimmer 2.2s linear infinite",
        floaty: "floaty 7s ease-in-out infinite",
        pulseRing: "pulseRing 2.4s cubic-bezier(0.2, 0.6, 0.35, 1) infinite",
        aurora: "aurora 22s ease-in-out infinite",
        sweep: "sweep 2.4s cubic-bezier(0.4, 0, 0.2, 1) infinite",
        marquee: "marquee 34s linear infinite",
        gradientShift: "gradientShift 9s ease infinite",
        breathe: "breathe 5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
