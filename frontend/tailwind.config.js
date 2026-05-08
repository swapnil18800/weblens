/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0a0c10",
        surface: "#11141a",
        accent: {
          DEFAULT: "#5b8cff",
          hover: "#7aa1ff",
          ring: "#5b8cff44",
        },
        good: "#10b981",
        warn: "#f59e0b",
        bad: "#f43f5e",
        info: "#0ea5e9",
        metric: "#8b5cf6",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        "2xs": "0.6875rem",
      },
      animation: {
        "fade-in": "fadeIn 200ms ease-out",
        "slide-down": "slideDown 150ms ease-out",
        "pulse-soft": "pulseSoft 1.6s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: 0, transform: "translateY(4px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
        slideDown: {
          "0%": { opacity: 0, transform: "translateY(-6px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: 1 },
          "50%": { opacity: 0.45 },
        },
      },
    },
  },
  plugins: [],
};
