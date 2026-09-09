// Voyage Outdoor design system.
//
// TWO PALETTES, ONE SHAPE. Every colour token exists in light and dark, and
// screens read them through useTheme() rather than importing a constant. That
// is the whole reason this file looks different from VoyageOS's theme.ts, which
// is a single light palette imported directly by 34 files — adding dark mode
// there means touching all 34. Here it means editing DARK below.
//
// Inherited unchanged, because they were right: the 4pt spacing grid, the three
// deliberate elevation steps, the radii, and one type scale where weight and
// tracking carry the hierarchy.
//
// Diverged deliberately: no destination-accent machinery. VoyageOS gives every
// trip its country's colour, which is travel identity. An adventure's identity
// is its terrain and its risk, and a headlamp warning that changes hue because
// the race is in Oman would be decoration standing where information goes.

import { useColorScheme } from 'react-native';

// ── the ramp ────────────────────────────────────────────────────────────────
// Inherited from VoyageOS (§19: same visual DNA) and pulled colder and deeper.
// Trail, not terminal: ink is nearly black so a night-time screen at minimum
// brightness is still legible, and the signal blue stays out of the amber and
// red that mean something here.

const RAMP = {
  ink:    '#08101C',
  slate:  '#0F1B2D',
  steel:  '#1D2E47',
  blue:   '#1268E3',
  sky:    '#4DA9FF',
  cyan:   '#6EE7FF',
};

export type Mode = 'light' | 'dark';

/** Every token, in both modes. Adding one means adding it twice — which is the
 *  point: a token that exists in only one mode is a screen that breaks in the
 *  other, discovered by a user rather than by the type checker. */
export type Palette = {
  brand: string; brandWash: string; onBrand: string;
  pageBg: string; card: string; sunken: string; raised: string;
  textPri: string; textSec: string; textMuted: string; onDark: string;
  hairline: string; hairlineStrong: string;
  success: string; danger: string; warning: string; warningInk: string;
  /** Non-negotiable kit, race cutoffs, "you do not own this". Reserved for
   *  things that are unsafe to ignore — if it is used for anything else it
   *  stops meaning anything. */
  critical: string;
  scrim: string;
};

const LIGHT: Palette = {
  brand: RAMP.blue,
  brandWash: 'rgba(18,104,227,0.08)',
  onBrand: '#FFFFFF',

  pageBg: '#F1F5FA',
  card: '#FFFFFF',
  sunken: '#E6EDF6',
  raised: '#FFFFFF',

  textPri: RAMP.ink,
  textSec: '#4A5A72',
  textMuted: '#77879F',
  onDark: '#FFFFFF',

  hairline: '#DDE5F0',
  hairlineStrong: '#C6D2E2',

  success: '#0E8F63',
  danger: '#D32B39',
  warning: '#E09A2B',
  // Amber for warning TEXT. The fill amber above reaches ~2.1:1 on white and
  // is unreadable as type; this one passes AA. Inherited wholesale from
  // VoyageOS, which found it the hard way.
  warningInk: '#A8590A',
  critical: '#C2261F',
  scrim: 'rgba(8,16,28,0.45)',
};

const DARK: Palette = {
  // Lifted, not the same blue. #1268E3 on a near-black card is a dim smudge;
  // an accent has to get LIGHTER as the surface gets darker to hold the same
  // apparent contrast.
  brand: RAMP.sky,
  brandWash: 'rgba(77,169,255,0.12)',
  onBrand: RAMP.ink,

  pageBg: RAMP.ink,
  card: RAMP.slate,
  sunken: '#0B1524',
  raised: RAMP.steel,

  textPri: '#E9F0F9',
  textSec: '#9FB0C7',
  textMuted: '#6C7E97',
  onDark: '#FFFFFF',

  hairline: '#1E2E45',
  hairlineStrong: '#2C4160',

  success: '#3DD39B',
  danger: '#FF6B72',
  warning: '#F2B44B',
  // On dark the fill amber is already legible as type, so warningInk is the
  // same value rather than a darker one. Kept as a separate token anyway: the
  // screens using it must not have to know which mode they are in.
  warningInk: '#F2B44B',
  critical: '#FF7A6E',
  scrim: 'rgba(0,0,0,0.6)',
};

export const PALETTES: Record<Mode, Palette> = { light: LIGHT, dark: DARK };

// ── scales — mode-independent ───────────────────────────────────────────────

/** 4pt grid. */
export const S = { 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40, 12: 48 } as const;

export const RA = { sm: 10, md: 14, lg: 18, xl: 24, pill: 999 } as const;

/** Minimum interactive size.
 *
 *  48, not the platform's 44. §19 asks for controls usable with light gloves,
 *  and a gloved fingertip has a contact patch roughly a third larger than a
 *  bare one — on top of which this app gets used while breathing hard. Every
 *  Pressable in the app either meets this or carries hitSlop to reach it. */
export const TAP = 48;

/** THE TYPEFACE.
 *
 *  §19 says inherit Satoshi from VoyageOS. Satoshi is a licensed face and its
 *  .otf files live in the VoyageOS repo; whether that licence covers a second
 *  application is a question for whoever bought it, not something to assume by
 *  copying three binaries across.
 *
 *  So this indirection: the app runs on the system face today, and dropping the
 *  files into app/assets/fonts/ plus registering them in App.tsx switches the
 *  whole type scale over with no other edit. `undefined` means "system default"
 *  to React Native, which is why the values below are not empty strings.
 */
export const F = {
  reg: undefined as string | undefined,
  med: undefined as string | undefined,
  bold: undefined as string | undefined,
};

export const T = {
  display: { fontFamily: F.bold, fontSize: 32, lineHeight: 36, letterSpacing: -0.8, fontWeight: '700' },
  h1:      { fontFamily: F.bold, fontSize: 24, lineHeight: 29, letterSpacing: -0.5, fontWeight: '700' },
  h2:      { fontFamily: F.bold, fontSize: 19, lineHeight: 24, letterSpacing: -0.3, fontWeight: '700' },
  title:   { fontFamily: F.med,  fontSize: 16, lineHeight: 21, letterSpacing: -0.1, fontWeight: '600' },
  body:    { fontFamily: F.reg,  fontSize: 15, lineHeight: 21, fontWeight: '400' },
  caption: { fontFamily: F.reg,  fontSize: 13, lineHeight: 18, fontWeight: '400' },
  label:   { fontFamily: F.bold, fontSize: 11, lineHeight: 14, letterSpacing: 0.8, fontWeight: '700' },
  /** Specs, mileage, elevation — anything that lines up in a column. */
  mono:    { fontFamily: 'Menlo', fontSize: 13, lineHeight: 18 },
} as const;

/** Three deliberate steps, not one blanket shadow.
 *
 *  Shadows are near-invisible on a dark surface, so dark mode carries the
 *  elevation on a border instead. Same token, same call site, different
 *  mechanism — which is what stops every card from having to branch. */
export function elevation(mode: Mode) {
  if (mode === 'dark') {
    return {
      low:  { borderWidth: 1, borderColor: DARK.hairline },
      mid:  { borderWidth: 1, borderColor: DARK.hairline },
      high: { borderWidth: 1, borderColor: DARK.hairlineStrong },
    };
  }
  return {
    low:  { shadowColor: RAMP.ink, shadowOpacity: 0.04, shadowRadius: 8,
            shadowOffset: { width: 0, height: 2 }, elevation: 1 },
    mid:  { shadowColor: RAMP.ink, shadowOpacity: 0.07, shadowRadius: 18,
            shadowOffset: { width: 0, height: 8 }, elevation: 3 },
    high: { shadowColor: RAMP.ink, shadowOpacity: 0.12, shadowRadius: 30,
            shadowOffset: { width: 0, height: 16 }, elevation: 8 },
  };
}

export type Theme = {
  mode: Mode;
  P: Palette;
  E: ReturnType<typeof elevation>;
};

/** The hook every screen uses.
 *
 *  Follows the OS. There is no in-app override yet and that is deliberate for
 *  Phase 1 — a three-way setting (light / dark / system) is a preference row, a
 *  stored value and a provider, and adding it later is cheap precisely because
 *  every screen already reads its colours from here rather than from a
 *  constant. What is expensive is the reverse, which is the trap VoyageOS is in.
 */
export function useTheme(): Theme {
  const scheme = useColorScheme();
  const mode: Mode = scheme === 'dark' ? 'dark' : 'light';
  return { mode, P: PALETTES[mode], E: elevation(mode) };
}

/** Readable ink on a filled colour, by relative luminance rather than by
 *  assumption — used wherever a status colour becomes a background. */
export function onColor(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? RAMP.ink : '#FFFFFF';
}

export function tint(hex: string, alpha = 0.14): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
