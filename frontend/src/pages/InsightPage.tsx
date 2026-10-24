import { Button } from '@alfalab/core-components/button';
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router';

import { useGenerateInsight, useInsight, useProfile, useSession } from '../api/hooks';
import type { ProductOffer } from '../api/types';
import { ErrorState } from '../components/common/ErrorState';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { ArrowLeft } from '../components/common/icons';
import { ConfidenceBadge, DirectionTag, ImpactBadge } from '../components/insight/Badges';
import { ClaimText } from '../components/insight/ClaimText';
import { FeedbackBar } from '../components/insight/FeedbackBar';
import { LeadModal } from '../components/insight/LeadModal';
import {
  ActionList,
  BankViewBlock,
  ConsequenceList,
  FeatureChips,
  Section,
  SourcesList,
  StatusNotice,
  WhatHappened,
} from '../components/insight/Sections';
import { SourceDrawer } from '../components/insight/SourceDrawer';
import { SourceDrawerContext } from '../components/insight/sourceContext';
import { formatDate } from '../lib/format';
import { SECTIONS } from '../lib/labels';
import { sendUiEvent } from '../lib/telemetry';
import styles from './InsightPage.module.css';

const ChainGraph = lazy(() => import('../components/insight/ChainGraph'));
const TracePanel = lazy(() => import('../components/agent/TracePanel'));
const ChatPanel = lazy(() => import('../components/chat/ChatPanel'));

export default function InsightPage() {
  const { insightId } = useParams();
  const q = useInsight(insightId);
  const session = useSession();
  const profile = useProfile();
  const regenerate = useGenerateInsight();
  const [drawer, setDrawer] = useState<{ ids: string[]; title: string }>({ ids: [], title: '' });
  const [product, setProduct] = useState<ProductOffer | null>(null);
  const [panel, setPanel] = useState<'trace' | 'chat' | null>(null);
  const api = useMemo(
    () => ({ open: (ids: string[], title = 'Источники') => setDrawer({ ids, title }) }),
    [],
  );

  useEffect(() => {
    if (insightId) sendUiEvent('insight_open', insightId);
  }, [insightId]);

  const featureLabels = useMemo(
    () =>
      Object.fromEntries(
        (profile.data?.profile.features ?? []).map((f) => [f.key, `${f.label}: ${f.value}`]),
      ),
    [profile.data],
  );

  if (q.isPending)
    return (
      <div className="page">
        <SkeletonCard lines={6} />
      </div>
    );
  if (q.isError || !q.data)
    return (
      <div className="page">
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </div>
    );
  const { insight, stale } = q.data;
  const role = session.data?.role ?? insight.role_generated_for;
  const risks = insight.consequences.filter((c) => c.kind === 'risk');
  const opps = insight.consequences.filter((c) => c.kind === 'opportunity');

  return (
    <SourceDrawerContext.Provider value={api}>
      <article className="page">
        <Link to="/feed" className={styles.back}>
          <ArrowLeft size={16} /> Лента
        </Link>
        <div className="row" style={{ gap: 14 }}>
          <DirectionTag direction={insight.direction} />
          <ImpactBadge level={insight.impact_level} />
          <ConfidenceBadge level={insight.confidence.level} reasons={insight.confidence.reasons} />
        </div>
        <h1 className={styles.headline}>{insight.headline}</h1>
        <p className={styles.why}>{insight.why_you}</p>
        <div className={styles.event}>
          {insight.event.title} · {insight.event.publishers.join(', ') || 'ваш текст'} ·{' '}
          {formatDate(insight.event.last_seen_at)}
        </div>
        <div className={styles.actions}>
          <Button
            view="secondary"
            size={40}
            onClick={() => {
              setPanel('trace');
              sendUiEvent('trace_open', insight.id);
            }}
          >
            Как мы пришли к выводу
          </Button>
          <Button
            view="secondary"
            size={40}
            onClick={() => {
              setPanel('chat');
              sendUiEvent('chat_open', insight.id);
            }}
          >
            Спросить аналитика
          </Button>
        </div>
        <StatusNotice
          insight={insight}
          stale={stale}
          onRecompute={stale ? () => regenerate.mutate(insight.event.id) : undefined}
        />

        <Section title={SECTIONS.what} id="what">
          <WhatHappened insight={insight} />
        </Section>

        <Section title={SECTIONS.why} id="why">
          <p style={{ margin: 0, fontSize: 17, lineHeight: '26px' }}>
            <ClaimText claim={insight.why_it_matters.summary} />
          </p>
          <FeatureChips keys={insight.why_it_matters.client_features_used} labels={featureLabels} />
          {insight.chain.nodes.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <Suspense fallback={<SkeletonCard />}>
                <ChainGraph chain={insight.chain} onOpenSources={(ids, title) => api.open(ids, title)} />
              </Suspense>
            </div>
          )}
        </Section>

        <Section title={SECTIONS.risks} id="risks">
          <ConsequenceList items={risks} empty="Существенных рисков не видим" />
        </Section>
        <Section title={SECTIONS.opportunities} id="opps">
          <ConsequenceList items={opps} empty="Явных возможностей не видим" />
        </Section>
        <Section title={SECTIONS.actions} id="actions">
          <ActionList
            actions={insight.actions}
            products={insight.products}
            role={role}
            onProduct={(p) => {
              setProduct(p);
              sendUiEvent('product_open', insight.id, { product_id: p.product_id });
            }}
          />
        </Section>
        <Section title={SECTIONS.bank} id="bank">
          <BankViewBlock insight={insight} />
        </Section>
        <Section title={SECTIONS.sources} id="sources">
          <SourcesList insight={insight} onOpen={(id) => api.open([id], 'Источник')} />
        </Section>
        <FeedbackBar detail={q.data} />
      </article>
      <SourceDrawer
        ids={drawer.ids}
        title={drawer.title}
        insightId={insight.id}
        onClose={() => setDrawer({ ids: [], title: '' })}
      />
      <LeadModal product={product} insightId={insight.id} onClose={() => setProduct(null)} />
      <Suspense fallback={null}>
        {panel === 'trace' && <TracePanel insightId={insight.id} onClose={() => setPanel(null)} />}
        {panel === 'chat' && <ChatPanel insightId={insight.id} onClose={() => setPanel(null)} />}
      </Suspense>
    </SourceDrawerContext.Provider>
  );
}
