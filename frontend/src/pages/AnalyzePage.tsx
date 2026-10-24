import { Button } from '@alfalab/core-components/button';
import { Input } from '@alfalab/core-components/input';
import { Tab, Tabs } from '@alfalab/core-components/tabs';
import { Textarea } from '@alfalab/core-components/textarea';
import { useQueryClient } from '@tanstack/react-query';
import { lazy, Suspense, useEffect, useState } from 'react';
import { Link } from 'react-router';

import { isApiError } from '../api/client';
import { useAnalyze, useAnalyzeHistory, useInsight, useSession } from '../api/hooks';
import { useRunEvents } from '../api/sse';
import { AgentTimeline } from '../components/agent/AgentTimeline';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { ConfidenceBadge, DirectionTag, ImpactBadge } from '../components/insight/Badges';
import { formatRelative } from '../lib/format';
import { ANALYZE_EXAMPLES, errorText } from '../lib/labels';
import { sendUiEvent } from '../lib/telemetry';

const ChainGraph = lazy(() => import('../components/insight/ChainGraph'));
const MIN_TEXT = 200;

function Stopwatch({ running }: { running: boolean }) {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [running]);
  return (
    <span className="h2" style={{ fontVariantNumeric: 'tabular-nums', margin: 0 }}>
      {Math.floor((now - start) / 1000)} с
    </span>
  );
}

function Result({ insightId }: { insightId: string }) {
  const q = useInsight(insightId);
  if (q.isPending) return <SkeletonCard lines={4} />;
  if (!q.data) return null;
  const ins = q.data.insight;
  return (
    <article className="card appear" style={{ marginTop: 20 }}>
      <div className="row" style={{ gap: 14 }}>
        <DirectionTag direction={ins.direction} />
        <ImpactBadge level={ins.impact_level} />
        <ConfidenceBadge level={ins.confidence.level} reasons={ins.confidence.reasons} />
      </div>
      <h2 style={{ fontSize: 24, lineHeight: '32px', margin: '12px 0 8px' }}>{ins.headline}</h2>
      <p style={{ margin: '0 0 16px', fontSize: 17 }}>{ins.why_you}</p>
      {ins.chain.nodes.length > 0 && (
        <Suspense fallback={<SkeletonCard />}>
          <ChainGraph chain={ins.chain} />
        </Suspense>
      )}
      <div style={{ marginTop: 16 }}>
        <Link to={`/insights/${ins.id}`}>
          <Button view="primary" size={48}>
            Открыть полностью
          </Button>
        </Link>
      </div>
    </article>
  );
}

export default function AnalyzePage() {
  const session = useSession();
  const qc = useQueryClient();
  const [tab, setTab] = useState<'url' | 'text'>('url');
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [title, setTitle] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const analyze = useAnalyze();
  const run = useRunEvents(runId);
  const history = useAnalyzeHistory();
  const running = !!runId && !run.end;

  useEffect(() => {
    if (run.end) void qc.invalidateQueries({ queryKey: ['analyzeHistory'] });
  }, [run.end, qc]);

  const canSubmit = tab === 'url' ? /^https?:\/\/\S+\.\S+/.test(url.trim()) : text.trim().length >= MIN_TEXT;
  const submit = () => {
    const body =
      tab === 'url' ? { url: url.trim() } : { text: text.trim(), title: title.trim() || undefined };
    sendUiEvent('analyze_submit', null, { mode: tab });
    analyze.mutate(body, { onSuccess: (r) => setRunId(r.run_id) });
  };
  const failedCode = run.end && run.end.status !== 'succeeded' ? run.end.error_code : null;

  return (
    <div className="page">
      <h1 className="h1">Проверить любую новость</h1>
      <p className="secondary" style={{ fontSize: 17, lineHeight: '26px', margin: '0 0 24px' }}>
        Вставьте ссылку или текст — покажем, как это влияет на {session.data?.company.name ?? 'вашу компанию'}
        .
      </p>
      <Tabs selectedId={tab} onChange={(_, { selectedId }) => setTab(selectedId as 'url' | 'text')} size="s">
        <Tab title="Ссылка" id="url">
          <div className="stack" style={{ paddingTop: 16 }}>
            <Input
              block
              label="Ссылка на новость"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://"
              disabled={running}
            />
          </div>
        </Tab>
        <Tab title="Текст" id="text">
          <div className="stack" style={{ paddingTop: 16 }}>
            <Input
              block
              label="Заголовок (необязательно)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={running}
            />
            <Textarea
              block
              label="Текст новости"
              value={text}
              onChange={(e) => setText(e.target.value)}
              autosize
              minRows={6}
              maxLength={20000}
              showCounter
              disabled={running}
              hint={
                text.trim().length > 0 && text.trim().length < MIN_TEXT
                  ? `Нужно не меньше ${MIN_TEXT} символов`
                  : undefined
              }
            />
          </div>
        </Tab>
      </Tabs>
      <div className="row" style={{ margin: '14px 0 18px' }}>
        <span className="caption">Примеры:</span>
        {ANALYZE_EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            disabled={running}
            onClick={() => {
              setTab('text');
              setText(ex.text);
              setTitle(ex.title);
            }}
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
            {ex.label}
          </button>
        ))}
      </div>
      <Button
        view="accent"
        size={56}
        onClick={submit}
        disabled={!canSubmit || running}
        loading={analyze.isPending}
      >
        Разобрать
      </Button>
      {analyze.isError && (
        <p role="alert" style={{ color: 'var(--ai-risk)' }}>
          {isApiError(analyze.error, 'blocked_url')
            ? errorText('blocked_url')
            : isApiError(analyze.error)
              ? analyze.error.message
              : errorText('internal')}
        </p>
      )}

      {runId && (
        <section style={{ marginTop: 28 }} aria-label="Ход разбора">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="secondary">
              {running
                ? 'Агент разбирает новость…'
                : run.end?.status === 'succeeded'
                  ? 'Готово'
                  : 'Разбор не удался'}
            </span>
            <Stopwatch key={runId} running={running} />
          </div>
          {failedCode && (
            <div className="card" role="alert" style={{ marginTop: 16 }}>
              <div className="h2">{errorText(failedCode)}</div>
              {(failedCode === 'fetch_failed' || failedCode === 'unsupported_content') && (
                <Button
                  view="secondary"
                  size={40}
                  onClick={() => {
                    setTab('text');
                    setRunId(null);
                  }}
                >
                  Вставить текст
                </Button>
              )}
            </div>
          )}
          {run.end?.status === 'succeeded' && run.end.insight_id && <Result insightId={run.end.insight_id} />}
          <details open={running} style={{ marginTop: 16 }}>
            <summary className="secondary" style={{ cursor: 'pointer' }}>
              Шаги агента
            </summary>
            <AgentTimeline events={run.events} live />
          </details>
        </section>
      )}

      {history.data && history.data.length > 0 && (
        <section style={{ marginTop: 40 }}>
          <h2 className="h2">Мои проверки</h2>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
            {history.data.map((h) => (
              <li
                key={h.run_id}
                className="row"
                style={{
                  justifyContent: 'space-between',
                  borderBottom: '1px solid var(--ai-border)',
                  padding: '8px 0',
                }}
              >
                <span>
                  {h.insight_id ? (
                    <Link to={`/insights/${h.insight_id}`}>{h.headline ?? h.input_label}</Link>
                  ) : (
                    h.input_label
                  )}
                  <div className="caption">
                    {h.input_label} · {formatRelative(h.created_at)}
                  </div>
                </span>
                <span className="caption">
                  {h.status === 'succeeded' ? '' : h.status === 'failed' ? 'не удалось' : 'в работе'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
