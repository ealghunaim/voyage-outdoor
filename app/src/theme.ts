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
// THE BRAND PALETTE, from the Voyage Outdoor design guide, section 5. The first
// five values are the guide's own hex codes and names; nothing here reinterprets
// them. What the guide does not answer is WHERE each one may be used, and that
// is not a stylistic question — it is a contrast question with a measurable
// answer, so the note below records the measurements rather than the taste.
//
//   Voyage Blue   #00A6FF   as text on the light page       2.43:1   FAILS AA
//                           as a fill under a white label   2.66:1   FAILS AA
//                           as text on Mountain Navy        6.38:1   passes
//   Deep Ocean    #0077CC   as a fill under a white label   4.66:1   passes
//                           as text on a white card        4.66:1   passes
//   Sky Ice       #AEE6FF   as text on Mountain Navy       12.57:1   passes
//   Slate         #6B7C8F   as muted text on white          4.28:1   passes
//
// So the hero colour cannot carry interaction in light mode. Voyage Blue is the
// DARK-mode brand, where it is genuinely excellent, and Deep Ocean carries light
// mode. Both are the guide's own colours — this splits them by surface rather
// than substituting anything, and it is the same principle the file already
// applied by hand: an accent has to get lighter as the surface gets darker.
//
// Voyage Blue still appears in light mode wherever contrast is not the job —
// the logo, brandWash fills, a progress bar — because a 3:1 non-text component
// is a different bar from 4.5:1 body copy.

const RAMP = {
  voyageBlue:   '#00A6FF',   // Trust · Outdoor      — hero, and dark-mode brand
  deepOcean:    '#0077CC',   // Depth · Stability    — light-mode interaction
  mountainNavy: '#0B1E2D',   // Strength · Adventure — dark page, icon plate
  skyIce:       '#AEE6FF',   // Clarity · Freedom    — accent on dark
  slate:        '#6B7C8F',   // Balance · Modern     — muted type

  // Not in the guide, and needed: a guide gives brand colours, not a whole UI.
  // These are the surfaces and hairlines between Mountain Navy and the page,
  // mixed toward navy so the dark mode reads as one family rather than as the
  // brand sitting on somebody else's grey.
  navyCard:     '#132A3C',
  navySunken:   '#081722',
  navyRaised:   '#1D3950',
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
  // Deep Ocean, not Voyage Blue — see the measurements on the ramp. A white
  // label on Voyage Blue is 2.66:1, which is a button nobody can read outdoors,
  // which is where this app is used.
  brand: RAMP.deepOcean,
  // The WASH is Voyage Blue. It sits behind content rather than under type, so
  // the hero colour belongs here: this is where the brand shows in light mode.
  brandWash: 'rgba(0,166,255,0.10)',
  onBrand: '#FFFFFF',

  pageBg: '#F1F5FA',
  card: '#FFFFFF',
  sunken: '#E6EDF6',
  raised: '#FFFFFF',

  textPri: RAMP.mountainNavy,
  textSec: '#43566B',
  textMuted: RAMP.slate,
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
  // Voyage Blue lands here, where it is genuinely excellent: 6.38:1 on Mountain
  // Navy as text, and 6.38:1 the other way for a navy label on a blue fill. The
  // same principle this file already applied by hand — an accent has to get
  // lighter as the surface gets darker — and the brand's hero colour happens to
  // be the lighter one.
  brand: RAMP.voyageBlue,
  brandWash: 'rgba(0,166,255,0.14)',
  onBrand: RAMP.mountainNavy,

  pageBg: RAMP.mountainNavy,
  card: RAMP.navyCard,
  sunken: RAMP.navySunken,
  raised: RAMP.navyRaised,

  // Sky Ice as primary type rather than a neutral white. It is 12.57:1 on
  // Mountain Navy — comfortably past AA — and it is the colour the guide gives
  // for clarity, so the dark mode reads as this brand at night rather than as a
  // generic dark theme.
  textPri: '#E7F4FD',
  textSec: '#A3BACE',
  textMuted: '#7B92A6',
  onDark: '#FFFFFF',

  hairline: '#1E3547',
  hairlineStrong: '#2E4A61',

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

/** THE TYPEFACE — Montserrat, and the Satoshi question is closed.
 *
 *  §19 said inherit Satoshi from VoyageOS, and Phase 1 left this as an
 *  indirection rather than copying three .otf files whose licence nobody had
 *  checked. The brand guide answers it: section 6 specifies MONTSERRAT, in
 *  Light / Regular / Medium / SemiBold / Bold. Montserrat is under the SIL Open
 *  Font License, so there is no licence to buy, no binary to smuggle across
 *  from another repo, and the question that was open for four phases is not a
 *  question any more.
 *
 *  Loaded from @expo-google-fonts/montserrat in App.tsx. The indirection stays
 *  because it cost nothing and it is what made this a one-file change.
 *
 *  These names must match the keys passed to useFonts() exactly — a typo here
 *  is not an error, it is a silent fall back to the system face, which looks
 *  almost right and is the hardest kind of wrong to notice.
 */
export const F = {
  reg: 'Montserrat_400Regular' as string | undefined,
  med: 'Montserrat_600SemiBold' as string | undefined,
  bold: 'Montserrat_700Bold' as string | undefined,
};

/** NO `fontWeight` ANYWHERE BELOW, and that is load-bearing rather than tidy.
 *
 *  The weight is already in the family name — Montserrat_700Bold IS the bold
 *  face. Naming a specific face AND asking for a weight makes iOS synthesise
 *  emboldening on top of a font that is already bold, and it does so AFTER
 *  measuring the string. The rendered glyphs come out wider than the box that
 *  was laid out for them, so the last character is clipped down the middle.
 *
 *  This shipped for exactly one run on the simulator and it looked like this:
 *  "Open locker" rendered as "Open locke", "Total weight" as "Total weigh",
 *  "Items" with the s sliced in half — on a button with an inch of clear space
 *  either side, which is what ruled out a layout cause. It was invisible for
 *  four phases only because the app was running on the system face, where
 *  fontWeight is the correct and only way to ask for bold.
 *
 *  The cost: if the font files ever fail to load, every size renders at the
 *  system regular weight and the hierarchy flattens. That is a legible
 *  degradation of a failure that needs a corrupt asset, weighed against
 *  clipping that every user sees on every screen.
 */
export const T = {
  display: { fontFamily: F.bold, fontSize: 32, lineHeight: 40, letterSpacing: -0.6 },
  h1:      { fontFamily: F.bold, fontSize: 24, lineHeight: 31, letterSpacing: -0.4 },
  h2:      { fontFamily: F.bold, fontSize: 19, lineHeight: 25, letterSpacing: -0.2 },
  title:   { fontFamily: F.med,  fontSize: 16, lineHeight: 22 },
  body:    { fontFamily: F.reg,  fontSize: 15, lineHeight: 22 },
  caption: { fontFamily: F.reg,  fontSize: 13, lineHeight: 19 },
  label:   { fontFamily: F.bold, fontSize: 11, lineHeight: 15, letterSpacing: 0.8 },
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
    low:  { shadowColor: RAMP.mountainNavy, shadowOpacity: 0.04, shadowRadius: 8,
            shadowOffset: { width: 0, height: 2 }, elevation: 1 },
    mid:  { shadowColor: RAMP.mountainNavy, shadowOpacity: 0.07, shadowRadius: 18,
            shadowOffset: { width: 0, height: 8 }, elevation: 3 },
    high: { shadowColor: RAMP.mountainNavy, shadowOpacity: 0.12, shadowRadius: 30,
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
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? RAMP.mountainNavy : '#FFFFFF';
}

export function tint(hex: string, alpha = 0.14): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
