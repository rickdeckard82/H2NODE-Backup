/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "media", // segue o prefers-color-scheme do navegador
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef6ff", 100: "#d9ebff", 200: "#b6d6ff", 300: "#86b9ff",
          400: "#4f92ff", 500: "#2b6cf6", 600: "#1a4fd8", 700: "#173fae",
          800: "#183889", 900: "#18306e",
        },
      },
    },
  },
  plugins: [],
};
