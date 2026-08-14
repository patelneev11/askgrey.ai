import { describe, expect, it } from 'vitest';

import { formatErrorDetail } from './api';

describe('formatErrorDetail', () => {
  it('passes through the string detail of a raised HTTPException', () => {
    expect(formatErrorDetail('Email is already registered')).toBe('Email is already registered');
  });

  it('joins the messages of a pydantic 422 issue list', () => {
    expect(
      formatErrorDetail([
        { loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' },
        { loc: ['body', 'password'], msg: 'String should have at least 12 characters' },
      ]),
    ).toBe('value is not a valid email address. String should have at least 12 characters');
  });

  it('returns undefined for shapes it cannot render, so the caller falls back', () => {
    expect(formatErrorDetail(undefined)).toBeUndefined();
    expect(formatErrorDetail({ unexpected: true })).toBeUndefined();
    expect(formatErrorDetail([{ type: 'value_error' }])).toBeUndefined();
  });
});
