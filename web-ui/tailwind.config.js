/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Climate-data aesthetic: deep ocean blue, sage green, warm earth.
        ink: {
          50: "#f5f7fa",
          100: "#e8edf3",
          200: "#cbd5e1",
          300: "#94a3b8",
          400: "#64748b",
          500: "#475569",
          600: "#334155",
          700: "#1e293b",
          800: "#0f172a",
          900: "#020617",
        },
        ocean: {
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
        },
        moss: {
          400: "#86efac",
          500: "#4ade80",
          600: "#16a34a",
        },
        amber: {
          400: "#fbbf24",
          500: "#f59e0b",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 3px 0 rgba(15, 23, 42, 0.08), 0 1px 2px -1px rgba(15, 23, 42, 0.05)",
        elevated: "0 10px 25px -5px rgba(15, 23, 42, 0.15), 0 8px 10px -6px rgba(15, 23, 42, 0.1)",
      },
    },
  },
  plugins: [],
};
