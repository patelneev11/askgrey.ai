/**
 * Schemes an outbound link is allowed to carry.
 *
 * A source URL, a patent hit and a cited passage all reach the page as text somebody else
 * supplied — a colleague's saved workspace, a third-party API, or a model's tool output — and
 * `javascript:` in an href runs as script when the link is clicked. Only the schemes a paper or
 * a record is ever served over are rendered as links; anything else loses its href and the
 * label stays as plain text.
 */
const ALLOWED_SCHEMES = new Set(["http:", "https:", "mailto:"]);

export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  const candidate = url.trim();
  if (!candidate) return undefined;
  // Same-origin routes and in-page anchors carry no scheme and are always ours.
  if (candidate.startsWith("/") || candidate.startsWith("#")) return candidate;
  try {
    return ALLOWED_SCHEMES.has(new URL(candidate).protocol)
      ? candidate
      : undefined;
  } catch {
    return undefined;
  }
}
