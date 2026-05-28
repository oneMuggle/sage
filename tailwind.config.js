/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: 'rgb(var(--color-primary-rgb) / <alpha-value>)',
          hover: 'rgb(var(--color-primary-hover-rgb) / <alpha-value>)',
        },
        secondary: 'rgb(var(--color-secondary-rgb) / <alpha-value>)',
        accent: 'rgb(var(--color-accent-rgb) / <alpha-value>)',
        bg: {
          DEFAULT: 'rgb(var(--color-bg-rgb) / <alpha-value>)',
          muted: 'rgb(var(--color-bg-muted-rgb) / <alpha-value>)',
          subtle: 'rgb(var(--color-bg-subtle-rgb) / <alpha-value>)',
          hover: 'rgb(var(--color-bg-hover-rgb) / <alpha-value>)',
          active: 'rgb(var(--color-bg-active-rgb) / <alpha-value>)',
        },
        surface: {
          DEFAULT: 'rgb(var(--color-surface-rgb) / <alpha-value>)',
          elevated: 'rgb(var(--color-surface-elevated-rgb) / <alpha-value>)',
          overlay: 'rgb(var(--color-surface-overlay-rgb) / <alpha-value>)',
        },
        text: {
          DEFAULT: 'rgb(var(--color-text-rgb) / <alpha-value>)',
          secondary: 'rgb(var(--color-text-secondary-rgb) / <alpha-value>)',
          muted: 'rgb(var(--color-text-muted-rgb) / <alpha-value>)',
          inverse: 'rgb(var(--color-text-inverse-rgb) / <alpha-value>)',
        },
        border: {
          DEFAULT: 'rgb(var(--color-border-rgb) / <alpha-value>)',
          hover: 'rgb(var(--color-border-hover-rgb) / <alpha-value>)',
        },
        success: 'rgb(var(--color-success-rgb) / <alpha-value>)',
        error: 'rgb(var(--color-error-rgb) / <alpha-value>)',
        warning: 'rgb(var(--color-warning-rgb) / <alpha-value>)',
        info: 'rgb(var(--color-info-rgb) / <alpha-value>)',
        overlay: 'var(--color-overlay)',
        role: {
          blue: 'rgb(var(--color-role-blue-rgb) / <alpha-value>)',
          'blue-text': 'rgb(var(--color-role-blue-text-rgb) / <alpha-value>)',
          green: 'rgb(var(--color-role-green-rgb) / <alpha-value>)',
          'green-text': 'rgb(var(--color-role-green-text-rgb) / <alpha-value>)',
          purple: 'rgb(var(--color-role-purple-rgb) / <alpha-value>)',
          'purple-text': 'rgb(var(--color-role-purple-text-rgb) / <alpha-value>)',
          orange: 'rgb(var(--color-role-orange-rgb) / <alpha-value>)',
          'orange-text': 'rgb(var(--color-role-orange-text-rgb) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
        chinese: ['Noto Sans SC', 'PingFang SC', 'sans-serif'],
      },
      spacing: {
        'space-1': 'var(--space-1)',
        'space-2': 'var(--space-2)',
        'space-3': 'var(--space-3)',
        'space-4': 'var(--space-4)',
        'space-5': 'var(--space-5)',
        'space-6': 'var(--space-6)',
        'space-8': 'var(--space-8)',
        'space-10': 'var(--space-10)',
        'space-12': 'var(--space-12)',
      },
      borderRadius: {
        'radius-sm': 'var(--radius-sm)',
        'radius-md': 'var(--radius-md)',
        'radius-lg': 'var(--radius-lg)',
        'radius-xl': 'var(--radius-xl)',
        'radius-2xl': 'var(--radius-2xl)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        xl: 'var(--shadow-xl)',
      },
      transitionDuration: {
        fast: '120ms',
        base: '200ms',
        slow: '300ms',
      },
    },
  },
  plugins: [],
}
