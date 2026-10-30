import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        fluid: {
          bg: '#09090b',          // Мягкий обсидиановый фон
          surface: '#141418',     // Графитовая плашка
          subtle: '#1c1c22',      // Ховеры и пилюли
          border: 'rgba(255, 255, 255, 0.06)',
          borderHover: 'rgba(255, 255, 255, 0.12)',
          accent: '#3b82f6',      // Precision Blue
          muted: '#71717a',
          dimmed: '#a1a1aa',
        },
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
        '4xl': '2rem',
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'Menlo', 'monospace'],
      },
      boxShadow: {
        'drawer': '-16px 0 48px -12px rgba(0, 0, 0, 0.75)',
        'capsule': '0 20px 40px -8px rgba(0, 0, 0, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.08)',
      },
    },
  },
  plugins: [],
};

export default config;
