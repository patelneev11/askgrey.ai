import styles from './Meter.module.css';

export type MeterTone = 'pipeline' | 'warning' | 'success' | 'neutral';

interface MeterProps {
  label: string;
  /** Rendered on the right of the label — the raw value behind the bar. */
  value: string;
  /** Fill fraction, 0–1. Clamped, so callers can pass raw ratios. */
  fraction: number;
  tone?: MeterTone;
}

/** Horizontal bar for a scored or predicted property: ADMET, review criteria, seat usage. */
export function Meter({ label, value, fraction, tone = 'pipeline' }: MeterProps) {
  const percent = Math.round(Math.min(1, Math.max(0, fraction)) * 100);

  return (
    <div className={styles.meter}>
      <div className={styles.head}>
        <span className={styles.label}>{label}</span>
        <span className={styles.value}>{value}</span>
      </div>
      <div
        className={styles.track}
        role="meter"
        aria-label={label}
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span className={[styles.fill, styles[tone]].join(' ')} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
