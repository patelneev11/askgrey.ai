import type { SVGProps } from 'react';

/**
 * Line icons drawn on a 24×24 grid with a 1.5px stroke, so they stay legible at the 16px
 * rail size and inherit colour from their container. Add new icons in this file only.
 */
export type IconName =
  | 'assistant'
  | 'literature'
  | 'screening'
  | 'protocol'
  | 'regulatory'
  | 'grants'
  | 'workspace'
  | 'audit'
  | 'settings'
  | 'chevronLeft'
  | 'chevronRight';

type IconProps = SVGProps<SVGSVGElement> & { name: IconName; size?: number };

const PATHS: Record<IconName, JSX.Element> = {
  // Speech bubble with a spark — the assistant that can reach the other tabs' tools.
  assistant: (
    <>
      <path d="M4.5 6A1.5 1.5 0 0 1 6 4.5h12A1.5 1.5 0 0 1 19.5 6v8A1.5 1.5 0 0 1 18 15.5H9l-4.5 4z" />
      <path d="M12 7.5l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5L8.5 11l2.5-1z" />
    </>
  ),
  // Stacked papers with a search lens — literature discovery.
  literature: (
    <>
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H12l3 3v4" />
      <path d="M15 7h-3V4" />
      <path d="M4 5.5v13A1.5 1.5 0 0 0 5.5 20h5" />
      <circle cx="16.5" cy="15.5" r="3.5" />
      <path d="m19.5 18.5 2 2" />
    </>
  ),
  // Benzene-style hexagon with a bond — compound screening.
  screening: (
    <>
      <path d="M12 3.5 19 7.5v9L12 20.5 5 16.5v-9z" />
      <path d="M12 8.5 15.5 10.5v4L12 16.5 8.5 14.5v-4z" />
    </>
  ),
  // Checklist on a clipboard — step-by-step protocols.
  protocol: (
    <>
      <path d="M9 4.5h6v2H9z" />
      <path d="M15 5.5h2.5A1.5 1.5 0 0 1 19 7v12a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 19V7a1.5 1.5 0 0 1 1.5-1.5H9" />
      <path d="m8.5 11.5 1.5 1.5 3-3" />
      <path d="M14.5 16.5h-6" />
    </>
  ),
  // Shield with a check — regulatory compliance.
  regulatory: (
    <>
      <path d="M12 3.5 19 6v6.5c0 4-3 6.8-7 8-4-1.2-7-4-7-8V6z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  // Award seal with ribbon — grant funding.
  grants: (
    <>
      <circle cx="12" cy="9.5" r="5.5" />
      <path d="m8.5 14.5-1 6 4.5-2.5 4.5 2.5-1-6" />
    </>
  ),
  // Building — the corporate workspace.
  workspace: (
    <>
      <path d="M5 20.5V6l7-2.5V20.5" />
      <path d="M12 9.5h7v11" />
      <path d="M3.5 20.5h17" />
      <path d="M8 9h1M8 12.5h1M8 16h1M15 13h1M15 16.5h1" />
    </>
  ),
  // Clock with history arrow — audit trail.
  audit: (
    <>
      <path d="M4 11.5a8 8 0 1 1 2.4 5.7" />
      <path d="M4 20v-4h4" />
      <path d="M12 7.5v4.5l3 1.8" />
    </>
  ),
  // Sliders — settings.
  settings: (
    <>
      <path d="M4 8h9M17 8h3M4 16h3M11 16h9" />
      <circle cx="15" cy="8" r="2" />
      <circle cx="9" cy="16" r="2" />
    </>
  ),
  chevronLeft: <path d="m14 6-6 6 6 6" />,
  chevronRight: <path d="m10 6 6 6-6 6" />,
};

export function Icon({ name, size = 16, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
