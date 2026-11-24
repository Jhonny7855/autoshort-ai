export type IconName =
  | "home"
  | "bolt"
  | "bulb"
  | "doc"
  | "film"
  | "layers"
  | "calendar"
  | "upload"
  | "bookmark"
  | "chart"
  | "chip"
  | "mic"
  | "gear"
  | "server"
  | "list"
  | "search"
  | "close"
  | "check"
  | "copy"
  | "download"
  | "external"
  | "play"
  | "pause"
  | "stop"
  | "refresh"
  | "sparkles"
  | "shield"
  | "clock"
  | "arrowRight"
  | "chevron"
  | "menu"
  | "logout"
  | "trash"
  | "plus"
  | "alert"
  | "eye";

const PATHS: Record<IconName, string> = {
  home: "M3 12l9-8 9 8v8a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z",
  bolt: "M12 2v4m0 12v4m10-10h-4M6 12H2m15.07-7.07l-2.83 2.83M9.76 14.24l-2.83 2.83m10.14 0l-2.83-2.83M9.76 9.76L6.93 6.93",
  bulb: "M12 3a6 6 0 00-3.6 10.8c.5.4.8 1 .8 1.6V17h5.6v-1.6c0-.6.3-1.2.8-1.6A6 6 0 0012 3zM9 21h6",
  doc: "M7 4h7l5 5v11a1 1 0 01-1 1H7a1 1 0 01-1-1V5a1 1 0 011-1zm7 0v5h5",
  film: "M4 6h11a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V7a1 1 0 011-1zm12 3l5-3v12l-5-3",
  layers: "M4 6h16M4 12h16M4 18h10",
  calendar: "M3 7h18v13a1 1 0 01-1 1H4a1 1 0 01-1-1zM8 3v4m8-4v4M3 11h18",
  upload: "M12 16V4m0 0L7 9m5-5l5 5M4 17v2a1 1 0 001 1h14a1 1 0 001-1v-2",
  bookmark: "M5 4h14a1 1 0 011 1v15l-8-4-8 4V5a1 1 0 011-1z",
  chart: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  chip: "M9 3h6l1 3h3v3l2 1v4l-2 1v3h-3l-1 3H9l-1-3H5v-3l-2-1v-4l2-1V6h3z",
  mic: "M12 3a3 3 0 013 3v6a3 3 0 01-6 0V6a3 3 0 013-3zm7 9a7 7 0 01-14 0M12 19v3",
  gear: "M12 15a3 3 0 100-6 3 3 0 000 6zM20.4 12a8.4 8.4 0 00-.1-1.3l2-1.6-2-3.4-2.4 1a8 8 0 00-2.2-1.3L15.3 2h-4l-.4 2.4a8 8 0 00-2.2 1.3l-2.4-1-2 3.4 2 1.6a8.4 8.4 0 000 2.6l-2 1.6 2 3.4 2.4-1a8 8 0 002.2 1.3l.4 2.4h4l.4-2.4a8 8 0 002.2-1.3l2.4 1 2-3.4-2-1.6c.07-.43.1-.86.1-1.3z",
  server: "M4 5h16v4H4zM4 11h16v4H4zM4 17h10v4H4z",
  list: "M4 4h16v16H4zm3 5h10M7 13h10M7 17h6",
  search: "M11 19a8 8 0 100-16 8 8 0 000 16zm10 2l-4.5-4.5",
  close: "M6 6l12 12M18 6L6 18",
  check: "M4 12.5l5 5L20 6.5",
  copy: "M9 9h10a1 1 0 011 1v10a1 1 0 01-1 1H9a1 1 0 01-1-1V10a1 1 0 011-1zM5 15H4a1 1 0 01-1-1V4a1 1 0 011-1h10a1 1 0 011 1v1",
  download: "M12 4v12m0 0l-5-5m5 5l5-5M4 19h16",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5",
  play: "M7 4l13 8-13 8z",
  pause: "M9 5v14M15 5v14",
  stop: "M6 6h12v12H6z",
  refresh: "M20 12a8 8 0 10-2.6 5.9M20 5v6h-6",
  sparkles: "M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6zM18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z",
  shield: "M12 3l8 3v6c0 4.4-3.4 7.7-8 9-4.6-1.3-8-4.6-8-9V6z",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zm0-13v5l4 2",
  arrowRight: "M4 12h15m0 0l-5-5m5 5l-5 5",
  chevron: "M9 6l6 6-6 6",
  menu: "M4 7h16M4 12h16M4 17h16",
  logout: "M15 12H3m4-4l-4 4 4 4m6-11h6a1 1 0 011 1v14a1 1 0 01-1 1h-6",
  trash: "M4 7h16M9 7V4h6v3m-8 0l1 14h8l1-14",
  plus: "M12 5v14M5 12h14",
  alert: "M12 3l9 17H3zM12 9v5m0 3v.5",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7zm10 3a3 3 0 100-6 3 3 0 000 6z",
};

export function Icon({ name, className = "h-[18px] w-[18px]", strokeWidth = 1.7 }: { name: IconName; className?: string; strokeWidth?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
