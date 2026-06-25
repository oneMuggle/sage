/**
 * 装饰性主题预设 — 5 套带封面图的扩展主题
 */
import type { ThemeColors } from './presets';

/** 装饰主题 */
export interface DecorativeTheme {
  id: string;
  name: string;
  description: string;
  /** 封面图路径（静态资源 URL） */
  cover: string;
  /** 封面加载失败时的渐变色降级 */
  gradientFrom: string;
  gradientTo: string;
  colors: ThemeColors;
  darkColors: ThemeColors;
}

// ─── Mint Blue ──────────────────────────

const mintBlueLight: ThemeColors = {
  primary: '#0d9488',
  primaryHover: '#0f766e',
  secondary: '#06b6d4',
  accent: '#14b8a6',
  bg: '#f0fdfa',
  bgMuted: '#ccfbf1',
  bgSubtle: '#d1fae5',
  bgHover: '#ccfbf1',
  bgActive: '#99f6e4',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#134e4a',
  textSecondary: '#5f7a76',
  textMuted: '#99b5b0',
  textInverse: '#ffffff',
  border: '#d1fae5',
  borderHover: '#a7f3d0',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#06b6d4',
  overlay: 'rgba(0,0,0,0.25)',
};

const mintBlueDark: ThemeColors = {
  primary: '#2dd4bf',
  primaryHover: '#5eead4',
  secondary: '#22d3ee',
  accent: '#14b8a6',
  bg: '#042f2e',
  bgMuted: '#0a3d3b',
  bgSubtle: '#115e59',
  bgHover: '#166d66',
  bgActive: '#134e4a',
  surface: '#053835',
  surfaceElevated: '#0a4542',
  text: '#f0fdfa',
  textSecondary: '#a7f3d0',
  textMuted: '#6ee7b7',
  textInverse: '#042f2e',
  border: '#115e59',
  borderHover: '#166d66',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#22d3ee',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Sakura ─────────────────────────────

const sakuraLight: ThemeColors = {
  primary: '#ec4899',
  primaryHover: '#db2777',
  secondary: '#f472b6',
  accent: '#fb7185',
  bg: '#fff0f5',
  bgMuted: '#fce7f3',
  bgSubtle: '#fbcfe8',
  bgHover: '#fce7f3',
  bgActive: '#f9a8d4',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#4a0429',
  textSecondary: '#831843',
  textMuted: '#be6b99',
  textInverse: '#ffffff',
  border: '#fbcfe8',
  borderHover: '#f9a8d4',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const sakuraDark: ThemeColors = {
  primary: '#f472b6',
  primaryHover: '#fb7185',
  secondary: '#f9a8d4',
  accent: '#fb7185',
  bg: '#2e061c',
  bgMuted: '#3d0a26',
  bgSubtle: '#501133',
  bgHover: '#631840',
  bgActive: '#4a0429',
  surface: '#350820',
  surfaceElevated: '#3f0d28',
  text: '#fff0f5',
  textSecondary: '#f9a8d4',
  textMuted: '#d4618c',
  textInverse: '#2e061c',
  border: '#501133',
  borderHover: '#631840',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#93c5fd',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Cyber Neon ─────────────────────────

const cyberNeonLight: ThemeColors = {
  primary: '#a855f7',
  primaryHover: '#9333ea',
  secondary: '#ec4899',
  accent: '#d946ef',
  bg: '#faf5ff',
  bgMuted: '#f3e8ff',
  bgSubtle: '#e9d5ff',
  bgHover: '#f3e8ff',
  bgActive: '#d8b4fe',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#3b0764',
  textSecondary: '#6b21a8',
  textMuted: '#a855f7',
  textInverse: '#ffffff',
  border: '#e9d5ff',
  borderHover: '#d8b4fe',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const cyberNeonDark: ThemeColors = {
  primary: '#c084fc',
  primaryHover: '#d8b4fe',
  secondary: '#f472b6',
  accent: '#e879f9',
  bg: '#1a0a2e',
  bgMuted: '#260f42',
  bgSubtle: '#331457',
  bgHover: '#401a6b',
  bgActive: '#3b0764',
  surface: '#1f0d38',
  surfaceElevated: '#280f48',
  text: '#faf5ff',
  textSecondary: '#d8b4fe',
  textMuted: '#a855f7',
  textInverse: '#1a0a2e',
  border: '#331457',
  borderHover: '#401a6b',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#60a5fa',
  overlay: 'rgba(0,0,0,0.6)',
};

// ─── Midnight Amber ─────────────────────

const midnightAmberLight: ThemeColors = {
  primary: '#d97706',
  primaryHover: '#b45309',
  secondary: '#92400e',
  accent: '#b45309',
  bg: '#fffbeb',
  bgMuted: '#fef3c7',
  bgSubtle: '#fde68a',
  bgHover: '#fef3c7',
  bgActive: '#fcd34d',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#1c1917',
  textSecondary: '#57534e',
  textMuted: '#a8a29e',
  textInverse: '#ffffff',
  border: '#e7e5e4',
  borderHover: '#d6d3d1',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const midnightAmberDark: ThemeColors = {
  primary: '#f59e0b',
  primaryHover: '#fbbf24',
  secondary: '#d97706',
  accent: '#fbbf24',
  bg: '#1c1917',
  bgMuted: '#292524',
  bgSubtle: '#3a3330',
  bgHover: '#44403c',
  bgActive: '#57534e',
  surface: '#211f1d',
  surfaceElevated: '#292524',
  text: '#fef3c7',
  textSecondary: '#d4a574',
  textMuted: '#a67c52',
  textInverse: '#1c1917',
  border: '#3a3330',
  borderHover: '#44403c',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#93c5fd',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Parchment ──────────────────────────

const parchmentLight: ThemeColors = {
  primary: '#92400e',
  primaryHover: '#78350f',
  secondary: '#a16207',
  accent: '#b45309',
  bg: '#fef3c7',
  bgMuted: '#fde68a',
  bgSubtle: '#fcd34d',
  bgHover: '#fde68a',
  bgActive: '#fbbf24',
  surface: '#fffbeb',
  surfaceElevated: '#fffbeb',
  text: '#1c1917',
  textSecondary: '#57534e',
  textMuted: '#a8a29e',
  textInverse: '#fef3c7',
  border: '#fde68a',
  borderHover: '#fcd34d',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const parchmentDark: ThemeColors = {
  primary: '#d97706',
  primaryHover: '#f59e0b',
  secondary: '#ca8a04',
  accent: '#f59e0b',
  bg: '#292016',
  bgMuted: '#3a2e1f',
  bgSubtle: '#4b3c28',
  bgHover: '#5c4a31',
  bgActive: '#6d583a',
  surface: '#2f2518',
  surfaceElevated: '#3a2e1f',
  text: '#fef3c7',
  textSecondary: '#d4a574',
  textMuted: '#a67c52',
  textInverse: '#292016',
  border: '#4b3c28',
  borderHover: '#5c4a31',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#93c5fd',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── 注册 ──────────────────────────────

export const decorativePresets: DecorativeTheme[] = [
  {
    id: 'mint-blue',
    name: 'Mint Blue',
    description: 'Mint green tones',
    cover: '/themes/covers/mint-blue.svg',
    gradientFrom: '#0d9488',
    gradientTo: '#06b6d4',
    colors: mintBlueLight,
    darkColors: mintBlueDark,
  },
  {
    id: 'sakura',
    name: 'Sakura',
    description: 'Cherry blossom pink',
    cover: '/themes/covers/sakura.svg',
    gradientFrom: '#ec4899',
    gradientTo: '#f472b6',
    colors: sakuraLight,
    darkColors: sakuraDark,
  },
  {
    id: 'cyber-neon',
    name: 'Cyber Neon',
    description: 'Neon purple and pink',
    cover: '/themes/covers/cyber-neon.svg',
    gradientFrom: '#a855f7',
    gradientTo: '#ec4899',
    colors: cyberNeonLight,
    darkColors: cyberNeonDark,
  },
  {
    id: 'midnight-amber',
    name: 'Midnight Amber',
    description: 'Dark background with amber highlights',
    cover: '/themes/covers/midnight-amber.svg',
    gradientFrom: '#d97706',
    gradientTo: '#f59e0b',
    colors: midnightAmberLight,
    darkColors: midnightAmberDark,
  },
  {
    id: 'parchment',
    name: 'Parchment',
    description: 'Vintage parchment texture',
    cover: '/themes/covers/parchment.svg',
    gradientFrom: '#92400e',
    gradientTo: '#b45309',
    colors: parchmentLight,
    darkColors: parchmentDark,
  },
];

/** 根据 id 查找装饰主题 */
export function findDecorativeThemeById(id: string): DecorativeTheme | undefined {
  return decorativePresets.find((t) => t.id === id);
}
