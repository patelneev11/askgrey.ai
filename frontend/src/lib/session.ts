/**
 * Where the signed-in session lives.
 *
 * The access token is held in module memory only — never in localStorage, where any injected
 * script can read it and where it survives long after the tab is closed. The refresh token is
 * not here at all: it is an HttpOnly cookie the browser attaches to /api/auth on its own, so
 * a reload restores the session by calling /auth/refresh rather than by reading storage.
 */

let accessToken: string | undefined;

export function getAccessToken(): string | undefined {
  return accessToken;
}

export function setAccessToken(token: string | undefined): void {
  accessToken = token;
}
