/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0F1419",
          soft: "#1C2128",
          muted: "#4A5159",
          fade: "#7A8189",
        },
        canvas: {
          DEFAULT: "#FAF7F2",
          raised: "#FFFFFF",
          sunken: "#F2EDE4",
          line: "#E8E2D6",
        },
        // Wahu deep navy — sidebar / login background.
        nav: {
          50: "#E7EBEF",
          100: "#C6D0D9",
          400: "#2F4555",
          500: "#1C2A37",
          600: "#16222D",
          700: "#101A22",
          800: "#0A1218",
          900: "#060B0F",
        },
        // Wahu mint — primary brand accent (logo mark color).
        accent: {
          50: "#E8FFF2",
          100: "#CCFFE3",
          200: "#B2FFD2",
          400: "#9AFFC1",
          500: "#5FE89B",
          600: "#2EBE71",
          700: "#1A8A50",
        },
        moss: {
          400: "#4A6F58",
          500: "#2F4F3A",
          600: "#23402D",
        },
        clay: {
          400: "#C97062",
          500: "#B85447",
          600: "#8E3A30",
        },
      },
      fontFamily: {
        display: ['"Fraunces"', "ui-serif", "Georgia", "serif"],
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      letterSpacing: {
        tightest: "-0.04em",
      },
      lineHeight: {
        relaxed2: "1.7",
      },
      boxShadow: {
        card: "0 1px 0 rgba(15, 20, 25, 0.04), 0 1px 2px rgba(15, 20, 25, 0.06)",
        elevated:
          "0 1px 0 rgba(15, 20, 25, 0.04), 0 4px 12px -2px rgba(15, 20, 25, 0.08), 0 8px 24px -8px rgba(46, 190, 113, 0.10)",
        floating:
          "0 2px 4px rgba(15, 20, 25, 0.06), 0 12px 32px -8px rgba(15, 20, 25, 0.16), 0 24px 48px -16px rgba(46, 190, 113, 0.14)",
        mint:
          "0 0 0 1px rgba(154, 255, 193, 0.35), 0 8px 32px -8px rgba(154, 255, 193, 0.25)",
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
    },
  },
  plugins: [],
};
