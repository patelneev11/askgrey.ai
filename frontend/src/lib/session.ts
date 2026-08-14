/** Where the signed-in session lives. Shared by the auth provider and the API client. */

export const ACCESS_KEY = 'askgrey:access-token';
export const REFRESH_KEY = 'askgrey:refresh-token';

export function getAccessToken(): string | undefined {
  return window.localStorage.getItem(ACCESS_KEY) ?? undefined;
}
