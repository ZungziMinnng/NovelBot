/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        // Inter 只管拉丁字母，中文不写字体名就全看系统兜底（Win 上常落到宋体），所以把中文黑体排在它后面
        sans: ['Inter', '"PingFang SC"', '"HarmonyOS Sans SC"', '"Microsoft YaHei UI"', '"Microsoft YaHei"', '"Noto Sans SC"', 'system-ui', 'sans-serif'],
        serif: ['Georgia', 'serif'],
        // 大标题用的宋体。Noto Serif SC 从 Google Fonts 按需取字形，取不到就退到系统宋体
        display: ['"Noto Serif SC"', '"Source Han Serif SC"', '"Songti SC"', 'STSong', 'SimSun', 'Georgia', 'serif'],
      },
      // 阴影统一走 --shadow-color：浅色基底是带蓝的灰，深色基底是纯黑加大浓度。
      // Tailwind 默认的 rgb(0 0 0 / .1) 在深色主题下等于没有，这是卡片「扁」的另一半原因
      boxShadow: {
        sm: '0 1px 2px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 0.5))',
        DEFAULT: '0 1px 2px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 0.6)), 0 2px 6px -1px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 0.5))',
        md: '0 2px 4px -1px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 0.6)), 0 6px 14px -4px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 0.8))',
        lg: '0 2px 6px -2px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 0.6)), 0 14px 30px -10px hsl(var(--shadow-color) / var(--shadow-strength))',
        xl: '0 4px 10px -4px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 0.6)), 0 24px 48px -16px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 1.2))',
        '2xl': '0 8px 16px -6px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 0.7)), 0 36px 72px -20px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 1.4))',
      },
      transitionTimingFunction: {
        'out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
}
