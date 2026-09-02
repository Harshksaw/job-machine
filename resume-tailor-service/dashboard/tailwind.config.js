/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "var(--jm-canvas)",
        surface: "var(--jm-surface)",
        raised: "var(--jm-raised)",
        line: "var(--jm-line)",
        ink: "var(--jm-ink)",
        muted: "var(--jm-muted)",
        dim: "var(--jm-dim)",
      },
    },
  },
  plugins: [],
};
