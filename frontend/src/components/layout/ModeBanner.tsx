import { useMeta, useSession } from '../../api/hooks';
import { useUiStore } from '../../app/session';
import { banners } from '../../lib/banners';

export function ModeBanner() {
  const meta = useMeta();
  const session = useSession();
  const dismissed = useUiStore((s) => s.bannerDismissed);
  const dismiss = useUiStore((s) => s.dismiss);
  const budget = session.data?.budget_mode ?? meta.data?.budget_mode;
  const list = banners(meta.data ? { ...meta.data, budget_mode: budget ?? 'normal' } : undefined).filter(
    (b) => !dismissed[b.key],
  );
  if (!list.length) return null;
  return (
    <div role="status" style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {list.map((b) => (
        <div
          key={b.key}
          className="caption"
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: 12,
            padding: '6px 16px',
            background: b.tone === 'warn' ? '#fff6e0' : 'var(--ai-bg-subtle)',
            color: 'var(--ai-text)',
          }}
        >
          <span>{b.text}</span>
          <button
            type="button"
            onClick={() => dismiss(b.key)}
            aria-label="Скрыть"
            style={{
              border: 0,
              background: 'transparent',
              cursor: 'pointer',
              color: 'var(--ai-text-secondary)',
              fontSize: 16,
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
