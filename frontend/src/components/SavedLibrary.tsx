import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/Button';
import { api } from '@/lib/api';
import { savedAt, type ArtifactKind, type SavedArtifactSummary } from '@/lib/library';
import { logger } from '@/lib/observability';
import { getAccessToken } from '@/lib/session';

import styles from './SavedLibrary.module.css';

interface SavedLibraryProps<T> {
  kind: ArtifactKind;
  /** What "Save" would keep. Null while the panel has no result, which disables saving. */
  current: { title: string; subtitle?: string; payload: T } | null;
  /** Hand a reopened result back to the panel that owns it. */
  onOpen: (payload: T) => void;
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

/**
 * Save this panel's result, and reopen anything saved earlier.
 *
 * Deliberately explicit: producing a result never writes anything, so a researcher decides what is
 * worth keeping. A reopened item is the response body the service returned, which is why the
 * caveats and review notices around it are the ones it was produced with — this component never
 * supplies its own.
 */
export function SavedLibrary<T>({ kind, current, onOpen }: SavedLibraryProps<T>) {
  const [items, setItems] = useState<SavedArtifactSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setItems(await api.listArtifacts(kind, getAccessToken()));
    } catch (cause) {
      // The list is a convenience; failing to load it must not break the panel around it.
      logger.warn('library.list_failed', { kind, message: message(cause, 'unknown') });
    }
  }, [kind]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const save = async () => {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveArtifact(
        { kind, title: current.title, subtitle: current.subtitle ?? '', payload: current.payload },
        getAccessToken(),
      );
      await refresh();
    } catch (cause) {
      setError(message(cause, 'That result could not be saved.'));
    } finally {
      setBusy(false);
    }
  };

  const open = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const stored = await api.loadArtifact<T>(id, getAccessToken());
      onOpen(stored.payload);
    } catch (cause) {
      setError(message(cause, 'That saved item could not be opened.'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteArtifact(id, getAccessToken());
      await refresh();
    } catch (cause) {
      setError(message(cause, 'That saved item could not be deleted.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.library} aria-label="Saved library">
      <header className={styles.header}>
        <h4 className={styles.title}>Saved</h4>
        <Button size="sm" variant="ghost" disabled={current === null || busy} onClick={() => void save()}>
          Save to library
        </Button>
      </header>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      {items.length === 0 ? (
        <p className={styles.hint}>
          Nothing saved yet. Saving keeps a result on your account exactly as it was produced,
          including its caveats, so you can reopen it after a reload.
        </p>
      ) : (
        <ul className={styles.list}>
          {items.map((item) => (
            <li className={styles.item} key={item.id}>
              <button
                type="button"
                className={styles.open}
                disabled={busy}
                onClick={() => void open(item.id)}
              >
                <span className={styles.itemTitle}>{item.title}</span>
                {item.subtitle && <span className={styles.itemMeta}>{item.subtitle}</span>}
                <span className={styles.itemMeta}>Saved {savedAt(item.created_at)}</span>
              </button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => void remove(item.id)}
                aria-label={`Delete ${item.title}`}
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
