/**
 * The assistant tab's wire types and its stream reader.
 *
 * A turn arrives as server-sent events rather than one response: prose in deltas, and a card per
 * tool the model ran. Mirrors `backend/app/services/chat/models.py`; the tool steps are what makes
 * an answer checkable, so they are first-class here rather than debug output.
 */

export type ChatReferenceKind = 'saved_work' | 'protocol' | 'literature_workspace';

export interface ChatReference {
  kind: ChatReferenceKind;
  /** Empty for the Literature workspace, which is one per account. */
  id: string;
}

export interface ChatCitation {
  label: string;
  source: string;
  identifier: string;
  url: string;
}

export interface ChatToolStep {
  id: string;
  tool: string;
  title: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  summary: string;
  citations: ChatCitation[];
  detail: unknown;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  steps: ChatToolStep[];
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}

/** One capability the assistant really has, as `GET /api/chat/tools` reports it. */
export interface ChatToolSummary {
  name: string;
  title: string;
  description: string;
  tab: string;
}

/**
 * The rules the tab has to show, as `GET /api/chat/limits` reports them.
 *
 * Shown rather than kept server-side: a researcher who can see the remaining budget and the scope
 * rule can work with them, whereas an unexplained refusal reads as a broken tab. A cap of 0 is
 * not enforced.
 */
export interface AssistantLimits {
  scope_version: string;
  scope_purpose: string;
  scope_refusal: string;
  daily_spent_usd: number;
  daily_cap_usd: number;
  monthly_spent_usd: number;
  monthly_cap_usd: number;
  exhausted_cap: '' | 'daily' | 'monthly';
  max_tool_steps: number;
  max_message_chars: number;
}

/** `$0.42 of $2.00` for a cap that is enforced, or the spend alone for one that is not. */
export function spendLabel(spent: number, cap: number): string {
  const used = `$${spent.toFixed(2)}`;
  return cap > 0 ? `${used} of $${cap.toFixed(2)}` : `${used} (no cap)`;
}

export type ChatEvent =
  | { type: 'text'; text: string }
  | { type: 'tool_start'; id: string; tool: string; title: string; arguments: Record<string, unknown> }
  | { type: 'tool_result'; step: ChatToolStep }
  | { type: 'notice'; message: string }
  | { type: 'done'; conversation_id: string; message_id: string }
  | { type: 'error'; message: string };

/**
 * Split an SSE body into the events it carries.
 *
 * Frames are separated by a blank line and a frame can straddle two reads, so the tail that has
 * not terminated yet is handed back rather than parsed. A frame the client does not recognise is
 * skipped: a newer server must not break an open tab.
 */
export function parseEventStream(buffer: string): { events: ChatEvent[]; rest: string } {
  const frames = buffer.split('\n\n');
  const rest = frames.pop() ?? '';
  const events: ChatEvent[] = [];
  for (const frame of frames) {
    for (const line of frame.split('\n')) {
      if (!line.startsWith('data:')) continue;
      try {
        const parsed = JSON.parse(line.slice('data:'.length).trim()) as ChatEvent;
        if (typeof parsed?.type === 'string') events.push(parsed);
      } catch {
        // A truncated or malformed frame loses that frame, never the turn.
      }
    }
  }
  return { events, rest };
}

/** Read a streamed turn to its end, handing each event to `onEvent` as it lands. */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseEventStream(buffer);
    buffer = rest;
    events.forEach(onEvent);
  }
  const { events } = parseEventStream(`${buffer}\n\n`);
  events.forEach(onEvent);
}

/** The tabs an @-reference can come from, for the picker's grouping. */
export const REFERENCE_LABELS: Record<ChatReferenceKind, string> = {
  saved_work: 'Saved work',
  protocol: 'Protocol',
  literature_workspace: 'Literature workspace',
};
