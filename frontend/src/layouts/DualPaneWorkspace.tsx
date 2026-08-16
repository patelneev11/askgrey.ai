import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

import styles from './DualPaneWorkspace.module.css';

const MIN_RATIO = 0.2;
const MAX_RATIO = 0.8;
const KEYBOARD_STEP = 0.02;

function clampRatio(ratio: number): number {
  return Math.min(MAX_RATIO, Math.max(MIN_RATIO, ratio));
}

interface DualPaneWorkspaceProps {
  /** Chat / agent canvas. */
  left: ReactNode;
  /** Data viewer, draft editor or visualization board. */
  right: ReactNode;
  /** Fraction of the width given to the left pane before the user drags the divider. */
  defaultRatio?: number;
  /** Persists the divider position per tab; omit to keep the split ephemeral. */
  storageKey?: string;
  leftLabel?: string;
  rightLabel?: string;
}

export function DualPaneWorkspace({
  left,
  right,
  defaultRatio = 0.42,
  storageKey,
  leftLabel = 'Assistant canvas',
  rightLabel = 'Data viewer',
}: DualPaneWorkspaceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ratio, setRatio] = useState(() => {
    if (!storageKey) return clampRatio(defaultRatio);
    const stored = window.localStorage.getItem(`askgrey:pane:${storageKey}`);
    const parsed = stored === null ? Number.NaN : Number.parseFloat(stored);
    return clampRatio(Number.isNaN(parsed) ? defaultRatio : parsed);
  });
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (storageKey) {
      window.localStorage.setItem(`askgrey:pane:${storageKey}`, ratio.toFixed(4));
    }
  }, [ratio, storageKey]);

  const updateFromPointer = useCallback((clientX: number) => {
    const container = containerRef.current;
    if (!container) return;
    const bounds = container.getBoundingClientRect();
    if (bounds.width === 0) return;
    setRatio(clampRatio((clientX - bounds.left) / bounds.width));
  }, []);

  useEffect(() => {
    if (!dragging) return;

    const handleMove = (event: PointerEvent) => {
      event.preventDefault();
      updateFromPointer(event.clientX);
    };
    const stop = () => setDragging(false);

    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    // Suppress text selection across the workspace for the duration of the drag.
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    return () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
  }, [dragging, updateFromPointer]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      setRatio((current) => clampRatio(current - KEYBOARD_STEP));
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      setRatio((current) => clampRatio(current + KEYBOARD_STEP));
    } else if (event.key === 'Home') {
      event.preventDefault();
      setRatio(clampRatio(defaultRatio));
    }
  };

  return (
    <div className={styles.workspace} ref={containerRef}>
      <div className={styles.pane} style={{ flexBasis: `${ratio * 100}%` }} aria-label={leftLabel}>
        {left}
      </div>
      <div
        role="separator"
        tabIndex={0}
        aria-orientation="vertical"
        aria-label="Resize workspace panes"
        aria-valuemin={Math.round(MIN_RATIO * 100)}
        aria-valuemax={Math.round(MAX_RATIO * 100)}
        aria-valuenow={Math.round(ratio * 100)}
        className={[styles.resizer, dragging ? styles.resizerActive : ''].join(' ')}
        onPointerDown={() => setDragging(true)}
        onDoubleClick={() => setRatio(clampRatio(defaultRatio))}
        onKeyDown={handleKeyDown}
      />
      <div
        className={styles.pane}
        style={{ flexBasis: `${(1 - ratio) * 100}%` }}
        aria-label={rightLabel}
      >
        {right}
      </div>
    </div>
  );
}
