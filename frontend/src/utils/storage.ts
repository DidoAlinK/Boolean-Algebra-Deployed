import type { CircuitMode, Preset } from '../api/types';

const KEYS = {
  expression: 'boolean-lab-expression',
  preset: 'boolean-lab-preset',
  mode: 'boolean-lab-mode',
  customPresets: 'boolean-lab-custom-presets',
} as const;

export interface AppPreferences { expression: string; preset: string; mode: CircuitMode }
const DEFAULTS: AppPreferences = { expression: '', preset: 'universal', mode: 'expression' };

function isMode(value: string | null): value is CircuitMode {
  return value === 'expression' || value === 'sop' || value === 'pos';
}

export function loadPreferences(): AppPreferences {
  const params = new URLSearchParams(window.location.search);
  const expression = params.get('f') ?? localStorage.getItem(KEYS.expression) ?? DEFAULTS.expression;
  const preset = params.get('preset') ?? localStorage.getItem(KEYS.preset) ?? DEFAULTS.preset;
  const modeCandidate = params.get('mode') ?? localStorage.getItem(KEYS.mode);
  return { expression, preset, mode: isMode(modeCandidate) ? modeCandidate : DEFAULTS.mode };
}

export function savePreferences(preferences: AppPreferences): void {
  localStorage.setItem(KEYS.expression, preferences.expression);
  localStorage.setItem(KEYS.preset, preferences.preset);
  localStorage.setItem(KEYS.mode, preferences.mode);
  const params = new URLSearchParams();
  if (preferences.expression) params.set('f', preferences.expression);
  params.set('preset', preferences.preset);
  params.set('mode', preferences.mode);
  window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}${window.location.hash}`);
}

export function loadCustomPresets(): Preset[] {
  try {
    const raw = localStorage.getItem(KEYS.customPresets);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed as Preset[] : [];
  } catch { return []; }
}

export function saveCustomPresets(presets: Preset[]): void {
  localStorage.setItem(KEYS.customPresets, JSON.stringify(presets));
}
