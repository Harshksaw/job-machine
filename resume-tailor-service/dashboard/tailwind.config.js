/** @type {import('tailwindcss').Config} */

// Components use `zinc-*` for neutrals and `teal-*` for the accent. Both
// scales are remapped here so the whole app shares one calm palette without
// touching every class name.
const neutral = {
  50: "#f6f6f8",
  100: "#ececf0",
  200: "#d7d8de",
  300: "#b5b7c0",
  400: "#8d909b",
  500: "#6c6f7a",
  600: "#3d4049",
  700: "#2b2d34",
  800: "#222329",
  900: "#191a1f",
  950: "#111216",
};

const accent = {
  50: "#eef0ff",
  100: "#e0e3ff",
  200: "#c6cbff",
  300: "#a4abfd",
  400: "#8189f8",
  500: "#6a70ef",
  600: "#5a5ee0",
  700: "#4a4dc4",
  800: "#3c3e9c",
  900: "#30327a",
  950: "#1d1e4a",
};

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        zinc: neutral,
        teal: accent,
        canvas: "var(--jm-canvas)",
        surface: "var(--jm-surface)",
        raised: "var(--jm-raised)",
        line: "var(--jm-line)",
        ink: "var(--jm-ink)",
        muted: "var(--jm-muted)",
        dim: "var(--jm-dim)",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
