/** @type {import('tailwindcss').Config} */
// Set default for tailwind 
module.exports = {
  content: ["./static/**/*.{html,js,css}"],
  theme: { extend: { colors: { primary: '#567A5C', secondary: '#CCEDC5' }, borderRadius: { 'none': '0px', 'sm': '4px', DEFAULT: '8px', 'md': '12px', 'lg': '16px', 'xl': '20px', '2xl': '24px', '3xl': '32px', 'full': '9999px', 'button': '8px' } } },
  plugins: [],
}
