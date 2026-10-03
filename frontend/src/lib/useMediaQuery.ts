import { useEffect, useState } from 'react';

/**
 * Where the workspace stops being a two-pane desktop layout. Phones and small tablets in
 * portrait sit below it; it is a little above an iPad's 768px portrait width so a tablet
 * held upright gets the stacked layout too, which is the one that fits a thumb.
 */
export const COMPACT_QUERY = '(max-width: 820px)';

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    // Rendered in jsdom and in a server-side build, neither of which has matchMedia.
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const list = window.matchMedia(query);
    setMatches(list.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

/** True on a phone-sized viewport, where panes stack and the sidebar becomes a drawer. */
export function useIsCompact(): boolean {
  return useMediaQuery(COMPACT_QUERY);
}
