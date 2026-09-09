import React from 'react';
import Svg, { Circle, Path } from 'react-native-svg';

export type TabKind = 'home' | 'adventures' | 'gear' | 'discover' | 'profile';

/** Line icons, 1.9 stroke, 24-grid.
 *
 *  Stroked rather than filled: a filled glyph needs a light interior to read
 *  against its own contour, which is the problem VoyageOS solved with a
 *  luminance `lift()` helper. Nothing here is tinted per-destination, so the
 *  simpler form is also the correct one. */
export function TabIcon({ kind, color, size = 24 }: {
  kind: TabKind; color: string; size?: number;
}) {
  const p = { stroke: color, strokeWidth: 1.9, strokeLinecap: 'round' as const,
              strokeLinejoin: 'round' as const, fill: 'none' };
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {kind === 'home' && (
        <>
          <Path d="M3.5 10.5 12 3.5l8.5 7" {...p} />
          <Path d="M5.5 9.5V20h13V9.5" {...p} />
        </>
      )}
      {/* A ridgeline. The one shape that says "outdoors" without a tree, a
          tent or a compass rose — all of which read as camping rather than as
          the thing this app plans. */}
      {kind === 'adventures' && (
        <>
          <Path d="M2.5 19h19L15 7l-3.5 6-2-3z" {...p} />
          <Circle cx={18} cy={6} r={2} {...p} />
        </>
      )}
      {/* A pack, not a box: this tab is what you own, and a box is storage. */}
      {kind === 'gear' && (
        <>
          <Path d="M6 9.5h12V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1z" {...p} />
          <Path d="M9 9.5V6a3 3 0 0 1 6 0v3.5" {...p} />
          <Path d="M9.5 14h5" {...p} />
        </>
      )}
      {kind === 'discover' && (
        <>
          <Circle cx={12} cy={12} r={8.5} {...p} />
          <Path d="M15 9l-2 4.2L9 15l2-4.2z" {...p} />
        </>
      )}
      {kind === 'profile' && (
        <>
          <Circle cx={12} cy={8.5} r={3.5} {...p} />
          <Path d="M4.5 20a7.5 7.5 0 0 1 15 0" {...p} />
        </>
      )}
    </Svg>
  );
}

export function Chevron({ color, size = 20 }: { color: string; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      <Path d="M9 5l7 7-7 7" stroke={color} strokeWidth={1.9}
            strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </Svg>
  );
}

export function Star({ color, filled, size = 18 }: {
  color: string; filled?: boolean; size?: number;
}) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      <Path
        d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8L3.6 9.7l5.8-.8z"
        stroke={color} strokeWidth={1.7} strokeLinejoin="round"
        fill={filled ? color : 'none'} />
    </Svg>
  );
}
