/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0f0f1a",
        card: "#1a1a2e",
      },
    },
  },
  plugins: [],
};
