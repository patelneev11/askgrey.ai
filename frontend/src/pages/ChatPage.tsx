import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/Button';
import { CaveatBand } from '@/components/CaveatBand';
import { EmptyState } from '@/components/EmptyState';
import { StatusPill } from '@/components/StatusPill';
import { api, ApiError } from '@/lib/api';
import type {
  ChatEvent,
  ChatMessage,
  ChatReference,
  ChatToolStep,
  ChatToolSummary,
  ConversationSummary,
} from '@/lib/chat';
import { readEventStream } from '@/lib/chat';
import type { SavedArtifactSummary } from '@/lib/library';
import type { SavedProtocolSummary } from '@/lib/protocols';
import { getAccessToken } from '@/lib/session';

import styles from './ChatPage.module.css';

/** One thing the researcher can point the assistant at, as the picker lists it. */
interface Mention {
  reference: ChatReference;
  label: string;
  detail: string;
}

const WORKSPACE_MENTION: Mention = {
  reference: { kind: 'literature_workspace', id: '' },
  label: 'Literature workspace',
  detail: 'Goal, papers and review table',
};

/**
 * A turn as the transcript holds it: the stored message plus any notice the stream carried, which
 * belongs to the answer it qualifies rather than disappearing when the stream closes.
 */
interface Turn extends ChatMessage {
  notices: string[];
}

/** A turn in flight: prose as it streams, plus the tool cards already resolved. */
interface Pending {
  text: string;
  steps: ChatToolStep[];
  running: { id: string; title: string } | null;
  notices: string[];
}

const EMPTY_PENDING: Pending = { text: '', steps: [], running: null, notices: [] };

function errorFrom(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 503) {
      return 'The assistant is not configured on this server: it needs an Anthropic API key.';
    }
    if (cause.status === 429) {
      return "This workspace has reached today's model call budget. It resets at 00:00 UTC.";
    }
    return cause.message;
  }
  return cause instanceof Error ? cause.message : 'The assistant could not be reached.';
}

function CitationLink({ label, source, identifier, url }: ChatToolStep['citations'][number]) {
  const text = identifier ? `${label} · ${identifier}` : label;
  return (
    <li className={styles.citation}>
      <span className={styles.citationSource}>{source}</span>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer noopener">
          {text}
        </a>
      ) : (
        <span>{text}</span>
      )}
    </li>
  );
}

/** What a tool was asked and what came back, so an answer can be checked rather than believed. */
function ToolCard({ step }: { step: ChatToolStep }) {
  const [open, setOpen] = useState(false);
  const args = Object.entries(step.arguments).filter(([, value]) => value !== null && value !== '');

  return (
    <div className={[styles.tool, step.ok ? '' : styles.toolFailed].filter(Boolean).join(' ')}>
      <div className={styles.toolHead}>
        <span className={styles.toolTitle}>{step.title}</span>
        <StatusPill tone={step.ok ? 'validated' : 'warning'}>
          {step.ok ? 'ran' : 'failed'}
        </StatusPill>
        <code className={styles.toolName}>{step.tool}</code>
      </div>
      <p className={styles.toolSummary}>{step.summary}</p>
      {step.citations.length > 0 && (
        <ul className={styles.citations}>
          {step.citations.map((citation) => (
            <CitationLink key={`${citation.source}-${citation.identifier}-${citation.label}`} {...citation} />
          ))}
        </ul>
      )}
      {args.length > 0 && (
        <>
          <button type="button" className={styles.toolToggle} onClick={() => setOpen(!open)}>
            {open ? 'Hide what it was asked' : 'Show what it was asked'}
          </button>
          {open && (
            <dl className={styles.toolArgs}>
              {args.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </>
      )}
    </div>
  );
}

function MessageBlock({ message }: { message: Turn }) {
  return (
    <article className={message.role === 'user' ? styles.asked : styles.answered}>
      <p className={styles.who}>{message.role === 'user' ? 'You' : 'Assistant'}</p>
      {message.steps.length > 0 && (
        <div className={styles.trace}>
          {message.steps.map((step) => (
            <ToolCard key={step.id} step={step} />
          ))}
        </div>
      )}
      <div className={styles.prose}>
        {message.text.split('\n').map((line, index) => (
          <p key={index}>{line}</p>
        ))}
      </div>
      {message.notices.map((notice) => (
        <p key={notice} className={styles.notice}>
          {notice}
        </p>
      ))}
    </article>
  );
}

export function ChatPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Turn[]>([]);
  const [tools, setTools] = useState<ChatToolSummary[]>([]);
  const [mentions, setMentions] = useState<Mention[]>([WORKSPACE_MENTION]);
  const [chosen, setChosen] = useState<Mention[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const transcript = useRef<HTMLDivElement>(null);

  const token = getAccessToken();

  useEffect(() => {
    let live = true;
    Promise.all([
      api.listConversations(token),
      api.chatTools(token),
      api.listArtifacts(undefined, token).catch((): SavedArtifactSummary[] => []),
      api.listProtocols(token).catch((): SavedProtocolSummary[] => []),
    ])
      .then(([threads, capabilities, artifacts, protocols]) => {
        if (!live) return;
        setConversations(threads);
        setTools(capabilities);
        setMentions([
          WORKSPACE_MENTION,
          ...artifacts.map((artifact) => ({
            reference: { kind: 'saved_work' as const, id: artifact.id },
            label: artifact.title,
            detail: artifact.subtitle || artifact.kind.replace(/_/g, ' '),
          })),
          ...protocols.map((protocol) => ({
            reference: { kind: 'protocol' as const, id: protocol.id },
            label: protocol.title,
            detail: `Protocol v${protocol.current_version}`,
          })),
        ]);
      })
      .catch((cause: unknown) => {
        if (live) setError(errorFrom(cause));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [token]);

  useEffect(() => {
    const pane = transcript.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [messages, pending]);

  const openThread = useCallback(
    (id: string) => {
      setConversationId(id);
      setError(null);
      api
        .loadConversation(id, token)
        .then((detail) =>
          setMessages(detail.messages.map((message) => ({ ...message, notices: [] }))),
        )
        .catch((cause: unknown) => setError(errorFrom(cause)));
    },
    [token],
  );

  const startThread = useCallback(() => {
    setConversationId(null);
    setMessages([]);
    setChosen([]);
    setError(null);
  }, []);

  const removeThread = useCallback(
    async (id: string) => {
      await api.deleteConversation(id, token).catch(() => undefined);
      setConversations((threads) => threads.filter((thread) => thread.id !== id));
      if (id === conversationId) startThread();
    },
    [conversationId, startThread, token],
  );

  const ask = useCallback(async () => {
    const question = draft.trim();
    if (!question || pending) return;
    setError(null);
    setDraft('');
    setPending(EMPTY_PENDING);
    const asked: Turn = {
      id: `local-${Date.now()}`,
      role: 'user',
      text: question,
      steps: [],
      notices: [],
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, asked]);

    try {
      let threadId = conversationId;
      if (!threadId) {
        const created = await api.startConversation(token);
        threadId = created.id;
        setConversationId(created.id);
      }
      const references = chosen.map((mention) => mention.reference);
      const body = await api.sendChatMessage(threadId, question, references, token);
      // The turn is accumulated here, not read back out of React state, so nothing streamed is
      // lost to a render that has not flushed yet.
      const turn: Pending = { ...EMPTY_PENDING };
      await readEventStream(body, (event: ChatEvent) => {
        switch (event.type) {
          case 'text':
            turn.text += event.text;
            break;
          case 'tool_start':
            turn.running = { id: event.id, title: event.title };
            break;
          case 'tool_result':
            turn.running = null;
            turn.steps = [...turn.steps, event.step];
            break;
          case 'notice':
            turn.notices = [...turn.notices, event.message];
            break;
          case 'error':
            setError(event.message);
            break;
          default:
            break;
        }
        setPending({ ...turn });
      });
      setPending(null);
      if (turn.text || turn.steps.length || turn.notices.length) {
        setMessages((current) => [
          ...current,
          {
            id: `answer-${Date.now()}`,
            role: 'assistant',
            text: turn.text,
            steps: turn.steps,
            notices: turn.notices,
            created_at: new Date().toISOString(),
          },
        ]);
      }
      setChosen([]);
      api.listConversations(token).then(setConversations).catch(() => undefined);
    } catch (cause: unknown) {
      setError(errorFrom(cause));
      setPending(null);
    }
  }, [chosen, conversationId, draft, pending, token]);

  const grouped = useMemo(() => {
    const byTab = new Map<string, ChatToolSummary[]>();
    for (const tool of tools) {
      byTab.set(tool.tab, [...(byTab.get(tool.tab) ?? []), tool]);
    }
    return [...byTab.entries()];
  }, [tools]);

  return (
    <div className={styles.page}>
      <aside className={styles.threads} aria-label="Conversations">
        <div className={styles.threadsHead}>
          <h2>Conversations</h2>
          <Button variant="secondary" onClick={startThread}>
            New
          </Button>
        </div>
        <ul className={styles.threadList}>
          {conversations.map((thread) => (
            <li key={thread.id}>
              <button
                type="button"
                aria-current={thread.id === conversationId}
                className={[styles.thread, thread.id === conversationId ? styles.threadOpen : '']
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => openThread(thread.id)}
              >
                <span className={styles.threadTitle}>{thread.title || 'Untitled'}</span>
                <span className={styles.threadMeta}>{thread.message_count} messages</span>
              </button>
              <button
                type="button"
                className={styles.threadDelete}
                aria-label={`Delete ${thread.title || 'conversation'}`}
                onClick={() => void removeThread(thread.id)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        {!loading && conversations.length === 0 && (
          <p className={styles.threadsEmpty}>Nothing asked yet. Threads you start appear here.</p>
        )}
        <div className={styles.capabilities}>
          <h3>What it can reach</h3>
          {grouped.map(([tab, group]) => (
            <p key={tab}>
              <span className={styles.capabilityTab}>{tab}</span>
              {group.map((tool) => tool.title).join(', ')}
            </p>
          ))}
        </div>
      </aside>

      <section className={styles.conversation} aria-label="Assistant">
        <header className={styles.head}>
          <div>
            <h1>Assistant</h1>
            <p>
              Ask a research question and it runs the same services the tabs do — PubMed, PubChem,
              ClinicalTrials.gov, descriptors and ADMET, patents, grants and drafting — showing
              every call it made.
            </p>
          </div>
          {pending && <StatusPill tone="running" pulse>Working</StatusPill>}
        </header>
        <CaveatBand label="Model output.">
          Answers, drafts and predictions here require expert review. ADMET and SAR values are
          predictions, not measurements; nothing said here is legal, regulatory or clinical advice.
          The assistant can read and draft, but it cannot save, edit or delete your work, and it
          cannot file anything in an external lab notebook.
        </CaveatBand>

        <div className={styles.transcript} ref={transcript}>
          {messages.length === 0 && !pending && (
            <EmptyState title="Ask about the work you already have">
              <p>
                Reference something you saved with the <strong>Reference</strong> button and it is
                read from your account — your Literature workspace, a saved screening or grants
                result, or a saved protocol. Nothing from another account is reachable.
              </p>
              <p>
                Good first questions: &ldquo;What did my last hERG prediction say, and how reliable
                is that endpoint?&rdquo;, &ldquo;Find trials for ziprasidone in the last five
                years&rdquo;, &ldquo;Am I eligible for SBIR Phase I as a 30-person company?&rdquo;
              </p>
            </EmptyState>
          )}
          {messages.map((message) => (
            <MessageBlock key={message.id} message={message} />
          ))}
          {pending && (
            <article className={styles.answered}>
              <p className={styles.who}>Assistant</p>
              {pending.steps.length > 0 && (
                <div className={styles.trace}>
                  {pending.steps.map((step) => (
                    <ToolCard key={step.id} step={step} />
                  ))}
                </div>
              )}
              {pending.running && (
                <p className={styles.running}>
                  <StatusPill tone="running" pulse>
                    {pending.running.title}
                  </StatusPill>
                </p>
              )}
              <div className={styles.prose}>
                {pending.text.split('\n').map((line, index) => (
                  <p key={index}>{line}</p>
                ))}
              </div>
              {pending.notices.map((notice) => (
                <p key={notice} className={styles.notice}>
                  {notice}
                </p>
              ))}
            </article>
          )}
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
        </div>

        <form
          className={styles.composer}
          onSubmit={(event) => {
            event.preventDefault();
            void ask();
          }}
        >
          {chosen.length > 0 && (
            <ul className={styles.chosen}>
              {chosen.map((mention) => (
                <li key={`${mention.reference.kind}-${mention.reference.id}`}>
                  @{mention.label}
                  <button
                    type="button"
                    aria-label={`Remove reference ${mention.label}`}
                    onClick={() =>
                      setChosen((current) => current.filter((item) => item !== mention))
                    }
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          {pickerOpen && (
            <ul className={styles.picker} aria-label="Your saved work">
              {mentions.map((mention) => (
                <li key={`${mention.reference.kind}-${mention.reference.id}`}>
                  <button
                    type="button"
                    onClick={() => {
                      setChosen((current) =>
                        current.some(
                          (item) =>
                            item.reference.kind === mention.reference.kind &&
                            item.reference.id === mention.reference.id,
                        )
                          ? current
                          : [...current, mention],
                      );
                      setPickerOpen(false);
                    }}
                  >
                    <span>{mention.label}</span>
                    <span className={styles.pickerDetail}>{mention.detail}</span>
                  </button>
                </li>
              ))}
              {mentions.length === 1 && (
                <li className={styles.pickerEmpty}>
                  Save a result in Screening, Regulatory, Grants or Protocol and it becomes
                  referenceable here.
                </li>
              )}
            </ul>
          )}
          <textarea
            className={styles.input}
            aria-label="Message the assistant"
            placeholder="Ask about a compound, a paper, a protocol, a filing or a grant…"
            value={draft}
            rows={3}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void ask();
              }
              if (event.key === '@') setPickerOpen(true);
            }}
          />
          <div className={styles.actions}>
            <Button
              variant="secondary"
              onClick={() => setPickerOpen(!pickerOpen)}
              aria-expanded={pickerOpen}
            >
              Reference
            </Button>
            <Button type="submit" disabled={!draft.trim() || pending !== null}>
              {pending ? 'Working…' : 'Ask'}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
