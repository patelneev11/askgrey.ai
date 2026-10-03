import { useEffect, useRef } from 'react';

/**
 * Fades a section in the first time it scrolls into view.
 *
 * The element starts hidden only when an observer and motion are both available, so a browser
 * without IntersectionObserver — and anyone who asks for reduced motion — gets the content
 * immediately rather than a blank page.
 */
export function useReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced || typeof IntersectionObserver !== 'function') {
      node.dataset.revealed = 'true';
      return;
    }

    node.dataset.reveal = 'pending';
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          node.dataset.revealed = 'true';
          observer.disconnect();
        }
      },
      { rootMargin: '0px 0px -12% 0px', threshold: 0.08 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return ref;
}
