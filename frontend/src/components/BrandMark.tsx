import type { SVGProps } from 'react';

const TILE = '#0c0c0e';
const GLYPH = '#00d9ff';

type BrandMarkProps = Omit<SVGProps<SVGSVGElement>, 'viewBox' | 'children'> & {
  size?: number;
  /** Draw the tile behind the glyph. Off when the mark sits on an already dark surface. */
  tile?: boolean;
};

/**
 * The askgrey glyph: an open ring crossed by a pulse trace, drawn on a 64×64 grid so it
 * stays crisp from the 16px favicon to the login card. Brand colours are fixed rather
 * than themed.
 */
export function BrandMark({ size = 24, tile = true, ...rest }: BrandMarkProps) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} role="img" aria-label="askgrey" {...rest}>
      {tile && <rect width="64" height="64" rx="13.5" fill={TILE} />}
      <g fill="none" stroke={GLYPH} strokeLinecap="round" strokeLinejoin="round">
        <path d="M42.1 14.6A20.1 20.1 0 1 0 49.3 42" strokeWidth="4.8" />
        <path d="M16.5 31.9h5.4l3.6-10 5.1 19.9 4.3-9.9H51" strokeWidth="3.2" />
      </g>
    </svg>
  );
}
