/**
 * Which of the two hostnames a page load is on.
 *
 * One bundle serves both: the marketing site on the apex and the signed-in product on its own
 * subdomain. The split is by hostname rather than by path so the product never has a public
 * route and the marketing pages never sit behind the auth guard.
 */

const DEFAULT_MARKETING_HOST = 'askgrey.app';
const DEFAULT_PRODUCT_HOST = 'lab.askgrey.app';

export const MARKETING_HOST = import.meta.env.VITE_MARKETING_HOST || DEFAULT_MARKETING_HOST;
export const PRODUCT_HOST = import.meta.env.VITE_PRODUCT_HOST || DEFAULT_PRODUCT_HOST;

export const MARKETING_ORIGIN = `https://${MARKETING_HOST}`;
export const PRODUCT_ORIGIN = `https://${PRODUCT_HOST}`;

/**
 * True on the marketing hostname and on `www.` in front of it.
 *
 * Localhost and preview hostnames are the product, because that is what a developer running
 * `npm run dev` is working on; `?site=marketing` opens the marketing pages there.
 */
export function isMarketingHost(location: { hostname: string; search: string }): boolean {
  const params = new URLSearchParams(location.search);
  const forced = params.get('site');
  if (forced === 'marketing') return true;
  if (forced === 'app') return false;

  const hostname = location.hostname.toLowerCase();
  return hostname === MARKETING_HOST || hostname === `www.${MARKETING_HOST}`;
}

/** An absolute URL into the product, for a marketing call to action. */
export function productUrl(
  path = '/',
  location: { hostname: string; search: string } | undefined = typeof window === 'undefined'
    ? undefined
    : window.location,
): string {
  if (location && !isMarketingHost(location)) {
    // Already on the product (or on localhost): keep the current origin so a local click does
    // not leave for production.
    return path;
  }
  return `${PRODUCT_ORIGIN}${path}`;
}
