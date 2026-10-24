import { Button } from '@alfalab/core-components/button';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useChat, useSendChat } from '../../api/hooks';
import { useRunEvents } from '../../api/sse';
import type { ChatMessage } from '../../api/types';
import { CHAT_SUGGESTIONS, errorText } from '../../lib/labels';
import { MiniSteps } from '../agent/MiniSteps';
import { Panel } from '../common/Panel';
import { ClaimText } from '../insight/ClaimText';
import { SourceDrawer } from '../insight/SourceDrawer';
import { SourceDrawerContext } from '../insight/sourceContext';

function Bubble({ m }: { m: ChatMessage }) {
  if (m.role === 'user') {
    return (
      <div
        style={{
          alignSelf: 'flex-end',
          maxWidth: '85%',
          background: 'var(--ai-text)',
          color: '#fff',
          padding: '10px 14px',
          borderRadius: '18px 18px 4px 18px',
        }}
      >
        {m.text}
      </div>
    );
  }
  return (
    <div
      style={{
        alignSelf: 'flex-start',
        maxWidth: '95%',
        background: 'var(--ai-bg-subtle)',
        padding: '12px 14px',
        borderRadius: '18px 18px 18px 4px',
      }}
    >
      <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', display: 'grid', gap: 8 }}>
        {(m.answer?.blocks ?? []).map((b, i) => (
          <li key={i} style={{ fontSize: 15, lineHeight: '22px' }}>
            <ClaimText claim={b} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ChatPanel({ insightId, onClose }: { insightId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [threadId, setThreadId] = useState<string | null>(null);
  const chat = useChat(insightId, threadId);
  const send = useSendChat(insightId);
  const [runId, setRunId] = useState<string | null>(null);
  const run = useRunEvents(runId);
  const [text, setText] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<string[]>([]);
  const bottom = useRef<HTMLDivElement>(null);
  const api = useMemo(() => ({ open: (ids: string[]) => setDrawer(ids) }), []);
  const thread = threadId ?? chat.data?.thread_id ?? null;
  const messages = chat.data?.messages ?? [];
  const busy = send.isPending || (!!runId && !run.end);
  const failed = run.end && run.end.status !== 'succeeded';

  useEffect(() => {
    if (run.end) {
      void qc.invalidateQueries({ queryKey: ['chat', insightId] });
    }
  }, [run.end, qc, insightId]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' });
  }, [messages.length, run.events.length]);

  const ask = (q: string) => {
    const message = q.trim();
    if (message.length < 2 || busy) return;
    setPending(message);
    setText('');
    send.mutate(
      { message, thread_id: thread },
      {
        onSuccess: (r) => {
          setThreadId(r.thread_id);
          setRunId(r.run_id);
        },
      },
    );
  };
  const followups = [...messages].reverse().find((m) => m.role === 'assistant')?.answer?.followups ?? [];
  const showPending = pending && !messages.some((m) => m.role === 'user' && m.text === pending);

  return (
    <SourceDrawerContext.Provider value={api}>
      <Panel open onClose={onClose} title="Спросить аналитика">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingBottom: 16, minHeight: 300 }}>
          {messages.length === 0 && !pending && (
            <p className="secondary" style={{ margin: 0 }}>
              Задайте вопрос по этому разбору — ответ будет со ссылками на источники.
            </p>
          )}
          {messages.map((m) => (
            <Bubble key={m.id} m={m} />
          ))}
          {showPending && (
            <Bubble m={{ id: -1, role: 'user', text: pending, answer: null, sources: [], created_at: '' }} />
          )}
          {busy && <MiniSteps events={run.events} />}
          {failed && (
            <div role="alert" className="secondary" style={{ color: 'var(--ai-risk)' }}>
              {errorText(run.end?.error_code)}{' '}
              <button
                type="button"
                onClick={() => pending && ask(pending)}
                style={{
                  border: 0,
                  background: 'none',
                  textDecoration: 'underline',
                  cursor: 'pointer',
                  font: 'inherit',
                }}
              >
                Повторить
              </button>
            </div>
          )}
          <div className="row">
            {(messages.length ? followups : CHAT_SUGGESTIONS).map((s) => (
              <button
                key={s}
                type="button"
                disabled={busy}
                onClick={() => ask(s)}
                style={{
                  border: '1px solid var(--ai-border)',
                  background: 'var(--ai-bg)',
                  borderRadius: 999,
                  padding: '4px 12px',
                  cursor: 'pointer',
                  font: 'inherit',
                  fontSize: 13,
                }}
              >
                {s}
              </button>
            ))}
          </div>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              ask(text);
            }}
            style={{ flexWrap: 'nowrap' }}
          >
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={1000}
              placeholder="Ваш вопрос"
              aria-label="Ваш вопрос"
              style={{
                flex: 1,
                padding: '12px 14px',
                borderRadius: 12,
                border: '1px solid var(--ai-border)',
                font: 'inherit',
              }}
            />
            <Button type="submit" view="accent" size={48} disabled={busy || text.trim().length < 2}>
              Спросить
            </Button>
          </form>
          <div ref={bottom} />
        </div>
      </Panel>
      <SourceDrawer
        ids={drawer}
        title="Источники ответа"
        insightId={insightId}
        onClose={() => setDrawer([])}
      />
    </SourceDrawerContext.Provider>
  );
}
