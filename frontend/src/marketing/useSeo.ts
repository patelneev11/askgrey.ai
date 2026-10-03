import { useEffect } from 'react';

import { MARKETING_ORIGIN } from '@/lib/hosts';

interface Seo {
  title: string;
  description: string;
  /** Path on the marketing host, e.g. `/security`. */
  path: string;
}

function setMeta(selector: string, attribute: string, name: string, content: string): void {
  let tag = document.head.querySelector<HTMLMetaElement>(selector);
  if (!tag) {
    tag = document.createElement('meta');
    tag.setAttribute(attribute, name);
    document.head.appendChild(tag);
  }
  tag.content = content;
}

/**
 * Title, description, canonical and social tags for a marketing page.
 *
 * index.html ships a baseline set for a crawler that does not run scripts; this replaces them
 * per route, so a shared link to /security does not describe the homepage.
 */
export function useSeo({ title, description, path }: Seo): void {
  useEffect(() => {
    const canonical = `${MARKETING_ORIGIN}${path}`;
    document.title = title;
    setMeta('meta[name="description"]', 'name', 'description', description);
    setMeta('meta[property="og:title"]', 'property', 'og:title', title);
    setMeta('meta[property="og:description"]', 'property', 'og:description', description);
    setMeta('meta[property="og:url"]', 'property', 'og:url', canonical);
    setMeta('meta[property="og:type"]', 'property', 'og:type', 'website');
    setMeta('meta[name="twitter:card"]', 'name', 'twitter:card', 'summary_large_image');
    setMeta('meta[name="twitter:title"]', 'name', 'twitter:title', title);
    setMeta('meta[name="twitter:description"]', 'name', 'twitter:description', description);

    let link = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'canonical';
      document.head.appendChild(link);
    }
    link.href = canonical;
  }, [title, description, path]);
}
