/**
 * 主题预设 — 每个主题包含完整的亮色 + 暗色配色
 */

/** 主题颜色集合 */
export interface ThemeColors {
  primary: string;
  primaryHover: string;
  secondary: string;
  accent: string;
  bg: string;
  bgMuted: string;
  bgSubtle: string;
  bgHover: string;
  bgActive: string;
  surface: string;
  surfaceElevated: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  textInverse: string;
  border: string;
  borderHover: string;
  success: string;
  error: string;
  warning: string;
  info: string;
  overlay: string;
}

/** 主题预设 */
export interface ThemePreset {
  id: string;
  name: string;
  description: string;
  colors: ThemeColors;
  darkColors: ThemeColors;
}

// ─── Indigo (默认) ───────────────────────────

const indigoLight: ThemeColors = {
  primary: '#4f46e5',
  primaryHover: '#4338ca',
  secondary: '#10b981',
  accent: '#f59e0b',
  bg: '#ffffff',
  bgMuted: '#f9fafb',
  bgSubtle: '#f3f4f6',
  bgHover: '#f3f4f6',
  bgActive: '#e0e7ff',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#111827',
  textSecondary: '#6b7280',
  textMuted: '#9ca3af',
  textInverse: '#ffffff',
  border: '#e5e7eb',
  borderHover: '#d1d5db',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const indigoDark: ThemeColors = {
  primary: '#818cf8',
  primaryHover: '#a5b4fc',
  secondary: '#34d399',
  accent: '#fbbf24',
  bg: '#0f172a',
  bgMuted: '#1f2937',
  bgSubtle: '#374151',
  bgHover: '#4b5563',
  bgActive: '#312e81',
  surface: '#111827',
  surfaceElevated: '#1f2937',
  text: '#f9fafb',
  textSecondary: '#d1d5db',
  textMuted: '#9ca3af',
  textInverse: '#ffffff',
  border: '#374151',
  borderHover: '#4b5563',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#60a5fa',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Sage Green ──────────────────────────────

const sageGreenLight: ThemeColors = {
  primary: '#059669',
  primaryHover: '#047857',
  secondary: '#0891b2',
  accent: '#d97706',
  bg: '#ffffff',
  bgMuted: '#f0fdf4',
  bgSubtle: '#ecfdf5',
  bgHover: '#f0fdf4',
  bgActive: '#d1fae5',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#111827',
  textSecondary: '#6b7280',
  textMuted: '#9ca3af',
  textInverse: '#ffffff',
  border: '#e5e7eb',
  borderHover: '#d1d5db',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const sageGreenDark: ThemeColors = {
  primary: '#34d399',
  primaryHover: '#6ee7b7',
  secondary: '#22d3ee',
  accent: '#fbbf24',
  bg: '#0a1a14',
  bgMuted: '#12241c',
  bgSubtle: '#1a3329',
  bgHover: '#234536',
  bgActive: '#064e3b',
  surface: '#0f1f18',
  surfaceElevated: '#162a21',
  text: '#f0fdf4',
  textSecondary: '#a7f3d0',
  textMuted: '#6ee7b7',
  textInverse: '#ffffff',
  border: '#1a3329',
  borderHover: '#234536',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#60a5fa',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Deep Ocean ──────────────────────────────

const oceanLight: ThemeColors = {
  primary: '#0053fd',
  primaryHover: '#0044cc',
  secondary: '#0891b2',
  accent: '#f59e0b',
  bg: '#f8faff',
  bgMuted: '#f0f4ff',
  bgSubtle: '#e8efff',
  bgHover: '#f0f4ff',
  bgActive: '#dbe8ff',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#17171a',
  textSecondary: '#52525b',
  textMuted: '#a1a1aa',
  textInverse: '#ffffff',
  border: '#e0e7ff',
  borderHover: '#c7d2fe',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const oceanDark: ThemeColors = {
  primary: '#ffe6cb',
  primaryHover: '#ffd4a8',
  secondary: '#22d3ee',
  accent: '#fbbf24',
  bg: '#0d2f86',
  bgMuted: '#09286f',
  bgSubtle: '#123a9e',
  bgHover: '#1a47b5',
  bgActive: '#1e3a8a',
  surface: '#0f2d7a',
  surfaceElevated: '#143590',
  text: '#ffe6cb',
  textSecondary: '#c4b5a0',
  textMuted: '#998877',
  textInverse: '#0d2f86',
  border: '#1a47b5',
  borderHover: '#2255cc',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#93c5fd',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Warm Ember ──────────────────────────────

const emberLight: ThemeColors = {
  primary: '#d97706',
  primaryHover: '#b45309',
  secondary: '#059669',
  accent: '#dc2626',
  bg: '#fffbeb',
  bgMuted: '#fef3c7',
  bgSubtle: '#fde68a',
  bgHover: '#fef3c7',
  bgActive: '#fde68a',
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

const emberDark: ThemeColors = {
  primary: '#fb923c',
  primaryHover: '#fdba74',
  secondary: '#34d399',
  accent: '#f87171',
  bg: '#1c0800',
  bgMuted: '#2a1200',
  bgSubtle: '#3d1c04',
  bgHover: '#502508',
  bgActive: '#78350f',
  surface: '#231000',
  surfaceElevated: '#2e1800',
  text: '#fef3c7',
  textSecondary: '#d4a574',
  textMuted: '#a67c52',
  textInverse: '#1c0800',
  border: '#3d1c04',
  borderHover: '#502508',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#93c5fd',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Mono ────────────────────────────────────

const monoLight: ThemeColors = {
  primary: '#404040',
  primaryHover: '#262626',
  secondary: '#525252',
  accent: '#737373',
  bg: '#ffffff',
  bgMuted: '#fafafa',
  bgSubtle: '#f5f5f5',
  bgHover: '#fafafa',
  bgActive: '#e5e5e5',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#171717',
  textSecondary: '#525252',
  textMuted: '#a3a3a3',
  textInverse: '#ffffff',
  border: '#e5e5e5',
  borderHover: '#d4d4d4',
  success: '#404040',
  error: '#525252',
  warning: '#737373',
  info: '#525252',
  overlay: 'rgba(0,0,0,0.25)',
};

const monoDark: ThemeColors = {
  primary: '#e5e5e5',
  primaryHover: '#ffffff',
  secondary: '#a3a3a3',
  accent: '#737373',
  bg: '#0a0a0a',
  bgMuted: '#171717',
  bgSubtle: '#262626',
  bgHover: '#262626',
  bgActive: '#404040',
  surface: '#0f0f0f',
  surfaceElevated: '#1a1a1a',
  text: '#fafafa',
  textSecondary: '#a3a3a3',
  textMuted: '#737373',
  textInverse: '#0a0a0a',
  border: '#262626',
  borderHover: '#404040',
  success: '#a3a3a3',
  error: '#a3a3a3',
  warning: '#737373',
  info: '#a3a3a3',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Cyberpunk ───────────────────────────────

const cyberpunkLight: ThemeColors = {
  primary: '#059669',
  primaryHover: '#047857',
  secondary: '#7c3aed',
  accent: '#ec4899',
  bg: '#f0fdf4',
  bgMuted: '#dcfce7',
  bgSubtle: '#bbf7d0',
  bgHover: '#dcfce7',
  bgActive: '#86efac',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#052e16',
  textSecondary: '#166534',
  textMuted: '#4ade80',
  textInverse: '#ffffff',
  border: '#bbf7d0',
  borderHover: '#86efac',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#7c3aed',
  overlay: 'rgba(0,0,0,0.25)',
};

const cyberpunkDark: ThemeColors = {
  primary: '#00ff41',
  primaryHover: '#39ff14',
  secondary: '#a855f7',
  accent: '#ec4899',
  bg: '#000a00',
  bgMuted: '#001a00',
  bgSubtle: '#002800',
  bgHover: '#003800',
  bgActive: '#004d00',
  surface: '#000f00',
  surfaceElevated: '#001a00',
  text: '#00ff41',
  textSecondary: '#39ff14',
  textMuted: '#00cc33',
  textInverse: '#000a00',
  border: '#003800',
  borderHover: '#004d00',
  success: '#00ff41',
  error: '#ff0040',
  warning: '#ffcc00',
  info: '#a855f7',
  overlay: 'rgba(0,0,0,0.6)',
};

// ─── 预设注册 ─────────────────────────────────

export const themePresets: ThemePreset[] = [
  {
    id: 'indigo',
    name: 'Indigo',
    description: '经典靛蓝，默认主题',
    colors: indigoLight,
    darkColors: indigoDark,
  },
  {
    id: 'sage-green',
    name: 'Sage Green',
    description: '自然清新的绿色调',
    colors: sageGreenLight,
    darkColors: sageGreenDark,
  },
  {
    id: 'ocean',
    name: 'Deep Ocean',
    description: '沉稳专业的深蓝色',
    colors: oceanLight,
    darkColors: oceanDark,
  },
  {
    id: 'ember',
    name: 'Warm Ember',
    description: '温暖舒适的橙棕调',
    colors: emberLight,
    darkColors: emberDark,
  },
  {
    id: 'mono',
    name: 'Mono',
    description: '极简灰度风格',
    colors: monoLight,
    darkColors: monoDark,
  },
  {
    id: 'cyberpunk',
    name: 'Cyberpunk',
    description: '霓虹绿科技感',
    colors: cyberpunkLight,
    darkColors: cyberpunkDark,
  },
];

/** 根据 id 获取主题预设 */
export function getThemeById(id: string): ThemePreset | undefined {
  return themePresets.find((t) => t.id === id);
}

/** 默认主题 id */
export const DEFAULT_THEME_ID = 'indigo';
