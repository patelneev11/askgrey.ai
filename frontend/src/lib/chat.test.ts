import { describe, expect, it, vi } from 'vitest';

import { parseEventStream, readEventStream, type ChatEvent } from './chat';

function bytes(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe('chat event stream', () => {
  it('hands back a frame that has not terminated yet', () => {
    const first = parseEventStream('data: {"type":"text","text":"He"}\n\ndata: {"type":"te');
    expect(first.events).toEqual([{ type: 'text', text: 'He' }]);
    expect(first.rest).toBe('data: {"type":"te');

    const second = parseEventStream(`${first.rest}xt","text":"llo"}\n\n`);
    expect(second.events).toEqual([{ type: 'text', text: 'llo' }]);
    expect(second.rest).toBe('');
  });

  it('skips a malformed frame without losing the ones around it', () => {
    const { events } = parseEventStream(
      'data: {"type":"text","text":"a"}\n\ndata: {not json\n\ndata: {"type":"notice","message":"cut short"}\n\n',
    );
    expect(events).toEqual([
      { type: 'text', text: 'a' },
      { type: 'notice', message: 'cut short' },
    ]);
  });

  it('reassembles a turn whose frames straddle reads', async () => {
    const seen: ChatEvent[] = [];
    await readEventStream(
      bytes(
        'data: {"type":"text","text":"Zip',
        'rasidone prolongs QT."}\n\ndata: {"type":"done","conversation_id":"c1","mess',
        'age_id":"m1"}',
      ),
      (event) => seen.push(event),
    );
    expect(seen).toEqual([
      { type: 'text', text: 'Ziprasidone prolongs QT.' },
      { type: 'done', conversation_id: 'c1', message_id: 'm1' },
    ]);
  });

  it('reads an empty body without calling back', async () => {
    const onEvent = vi.fn();
    await readEventStream(bytes(), onEvent);
    expect(onEvent).not.toHaveBeenCalled();
  });
});
