import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "#F1F5F9",
        card: "#FFFFFF",
        "card-alt": "#F8FAFC",
        surface: "#F1F5F9",
        border: "#E2E8F0",
        "border-light": "#F1F5F9",
        sidebar: "#FFFFFF",
        "sidebar-dark": "#1E3A5F",
        "sidebar-dark-hover": "#2A4A75",
        "sidebar-dark-active": "#2563EB",
        accent: {
          blue: "#3B82F6",
          cyan: "#06B6D4",
          gold: "#F59E0B",
          red: "#EF4444",
          green: "#10B981",
          purple: "#8B5CF6",
          orange: "#F97316",
          pink: "#EC4899",
        },
        text: {
          primary: "#0F172A",
          secondary: "#475569",
          muted: "#94A3B8",
          inverse: "#FFFFFF",
        },
      },
      fontFamily: {
        display: ['"DM Sans"', "sans-serif"],
        body: ['"IBM Plex Sans"', "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
      boxShadow: {
        card: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
        "card-hover": "0 4px 16px rgba(0,0,0,0.1), 0 2px 6px rgba(0,0,0,0.06)",
        sidebar: "4px 0 12px rgba(0,0,0,0.08)",
        badge: "0 1px 2px rgba(0,0,0,0.05)",
      },
      fontSize: {
        "page-title": ["1.75rem", { lineHeight: "2.25rem" }],
        "section-title": ["1.125rem", { lineHeight: "1.5rem" }],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
