import type { ChangeEvent, ReactNode } from 'react';

import { Button } from '@/components/Button';

import styles from './regulatory.module.css';

let sequence = 0;

/** Stable-enough ids for label/control pairing inside repeated row editors. */
function nextId(prefix: string): string {
  sequence += 1;
  return `${prefix}-${sequence}`;
}

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  maxLength?: number;
  required?: boolean;
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  hint,
  maxLength,
  required,
}: TextFieldProps) {
  const id = nextId('field');

  return (
    <p className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={styles.input}
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        required={required}
        autoComplete="off"
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
      />
      {hint && <span className={styles.hint}>{hint}</span>}
    </p>
  );
}

interface TextAreaFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  rows?: number;
  maxLength?: number;
}

export function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
  hint,
  rows = 8,
  maxLength,
}: TextAreaFieldProps) {
  const id = nextId('area');

  return (
    <p className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <textarea
        id={id}
        className={styles.textarea}
        value={value}
        rows={rows}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
      />
      {hint && <span className={styles.hint}>{hint}</span>}
    </p>
  );
}

interface SelectFieldProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}

export function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
}: SelectFieldProps<T>) {
  const id = nextId('select');

  return (
    <p className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className={styles.input}
        value={value}
        onChange={(event: ChangeEvent<HTMLSelectElement>) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </p>
  );
}

interface RowGroupProps {
  title: string;
  /** What the rows are for, and what leaving them empty means for the draft. */
  hint: string;
  addLabel: string;
  onAdd: () => void;
  children: ReactNode;
}

/** A repeatable block of structured rows — dose groups, findings, evidence records. */
export function RowGroup({ title, hint, addLabel, onAdd, children }: RowGroupProps) {
  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>{title}</legend>
      <p className={styles.hint}>{hint}</p>
      {children}
      <Button size="sm" onClick={onAdd}>
        {addLabel}
      </Button>
    </fieldset>
  );
}

export function Row({ onRemove, children }: { onRemove: () => void; children: ReactNode }) {
  return (
    <div className={styles.row}>
      <div className={styles.rowFields}>{children}</div>
      <Button size="sm" variant="ghost" onClick={onRemove} aria-label="Remove row">
        Remove
      </Button>
    </div>
  );
}
