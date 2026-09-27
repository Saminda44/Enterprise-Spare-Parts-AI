/** @type {import('tailwindcss').Config} */
export default {
  content: ["./planning/index.html", "./planning/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          blue:   "#4361EE",
          green:  "#2CC56F",
          amber:  "#FFC107",
          red:    "#EF4444",
          purple: "#7C3AED",
          teal:   "#06B6D4",
          slate:  "#64748B",
        },
        sidebar: "#0F172A",
        surface: "#F6F8FB",
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui"] },
    },
  },
  plugins: [],
}
