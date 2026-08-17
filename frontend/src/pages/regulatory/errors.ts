import { ApiError } from '@/lib/api';

/**
 * What to put on screen when a regulatory call fails.
 *
 * The backend already sanitises its own messages (nothing from the upstream model or the
 * submitted study data reaches the client), so an ApiError message is safe to show. Anything
 * else — a network failure, a parse failure — is reduced to a generic line rather than risking
 * an exception string that quotes part of a request.
 */
export function errorMessage(cause: unknown): string {
  if (cause instanceof ApiError) {
    return cause.message;
  }
  return 'The request could not be completed. Check your connection and try again.';
}
