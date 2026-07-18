/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Warm-tinted charcoal surfaces — deliberately NOT near-black.
        ink: {
          900: "#17150f", // deepest chrome
          850: "#1c1a13",
          800: "#221f18", // primary surface
          750: "#2a271e",
          700: "#332f24", // raised panels
          600: "#413c2e",
          500: "#54503f",
        },
        parchment: {
          100: "#f4efe3", // transcript reading text
          200: "#e7e0cf",
          400: "#b9b19b", // secondary text
          600: "#8a8370", // muted / timecodes
        },
        // The single restrained accent — playhead + active states only.
        accent: {
          DEFAULT: "#d9a441",
          soft: "#b98a37",
          glow: "#f0c368",
        },
        // Ink-red redaction for cut/struck words.
        redact: {
          DEFAULT: "#b0553f",
          dim: "#7a4433",
        },
      },
      fontFamily: {
        // Transcript: a real reading face (manuscript feel).
        reading: [
          "Iowan Old Style",
          "Palatino Linotype",
          "Georgia",
          "Cambria",
          "serif",
        ],
        ui: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SF Mono",
          "Cascadia Code",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        transcript: ["1.0625rem", { lineHeight: "1.9" }],
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        shimmer: "shimmer 1.8s linear infinite",
      },
    },
  },
  plugins: [],
};
