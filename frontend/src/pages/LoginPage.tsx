import { Button } from '@alfalab/core-components/button';
import { Input } from '@alfalab/core-components/input';
import { SegmentedControl, Segment } from '@alfalab/core-components/segmented-control';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { isApiError } from '../api/client';
import { useDemoCompanies, useLogin, useMeta } from '../api/hooks';
import type { CompanySummary, Role } from '../api/types';
import { Logo } from '../components/layout/TopBar';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { ROLE, ROLE_SHORT } from '../lib/labels';
import styles from './LoginPage.module.css';

const ROLES: Role[] = ['cfo', 'treasurer', 'owner'];

function CompanyCard({
  c,
  selected,
  onSelect,
}: {
  c: CompanySummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`${styles.company} ${selected ? styles.selected : ''}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <div className={styles.name}>{c.name}</div>
      <div className="caption">
        {c.industry_name}
        {c.region_name ? ` · ${c.region_name}` : ''}
      </div>
      {c.story && <div className={styles.story}>{c.story}</div>}
    </button>
  );
}

export default function LoginPage() {
  const meta = useMeta();
  const demoMode = meta.data?.demo_mode ?? true;
  const [query, setQuery] = useState('');
  const [juryOpen, setJuryOpen] = useState(false);
  const [code, setCode] = useState('');
  const demo = useDemoCompanies();
  const search = useDemoCompanies(query.trim().length >= 2 ? query.trim() : undefined);
  const [picked, setPicked] = useState<CompanySummary | null>(null);
  const [pickedRole, setRole] = useState<Role | null>(null);
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();
  const demoList = (demo.data ?? []).filter((c) => c.is_demo);
  const selected = picked ?? demoList[0] ?? null;
  const role: Role = pickedRole ?? selected?.default_role ?? 'cfo';

  const choose = (c: CompanySummary) => {
    setPicked(c);
    setRole(null);
  };

  const submit = () => {
    if (!selected) return;
    login.mutate(
      { company_id: selected.company_id, role, jury_code: code.trim() || null },
      {
        onSuccess: () =>
          navigate((location.state as { from?: string } | null)?.from ?? '/', { replace: true }),
      },
    );
  };

  const showSearch = demoMode || juryOpen;
  const extra = query.trim().length >= 2 ? (search.data ?? []).filter((c) => !c.is_demo) : [];

  return (
    <div className={styles.wrap}>
      <div className={styles.hero}>
        <Logo />
        <h1 className={styles.title}>Новости, которые важны вашему бизнесу</h1>
        <p className="secondary" style={{ fontSize: 17, lineHeight: '26px' }}>
          Выберите компанию и роль — покажем, как события в экономике влияют на неё через поставщиков,
          покупателей и макрофакторы.
        </p>
      </div>

      {demo.isPending ? (
        <SkeletonCard />
      ) : (
        <div className={styles.grid} role="list" aria-label="Демо-компании">
          {demoList.map((c) => (
            <CompanyCard
              key={c.company_id}
              c={c}
              selected={selected?.company_id === c.company_id}
              onSelect={() => choose(c)}
            />
          ))}
        </div>
      )}

      <div className={styles.footer}>
        <SegmentedControl
          size={40}
          selectedId={role}
          onChange={(id) => setRole(id as Role)}
          className={styles.roles}
        >
          {ROLES.map((r) => (
            <Segment key={r} id={r} title={ROLE_SHORT[r]} />
          ))}
        </SegmentedControl>
        <Button
          view="accent"
          size={56}
          onClick={submit}
          loading={login.isPending}
          disabled={!selected}
          style={{ minWidth: 280 }}
        >
          Войти{selected ? ` как ${ROLE[role].toLowerCase()}` : ''}
        </Button>
        {login.isError && (
          <div role="alert" className="secondary" style={{ color: 'var(--ai-risk)' }}>
            {isApiError(login.error, 'forbidden')
              ? login.error.message
              : 'Не удалось войти, попробуйте ещё раз'}
          </div>
        )}
      </div>

      <div className={styles.jury}>
        {!demoMode && (
          <button
            type="button"
            className={styles.juryToggle}
            onClick={() => setJuryOpen((v) => !v)}
            aria-expanded={juryOpen}
          >
            Я из жюри {juryOpen ? '▴' : '▾'}
          </button>
        )}
        {showSearch && (
          <div className="stack" style={{ marginTop: 12 }}>
            <div className="secondary">Другая целевая компания — найдите по названию</div>
            <Input block label="Компания" value={query} onChange={(e) => setQuery(e.target.value)} />
            {!demoMode && (
              <Input
                block
                label="Код жюри"
                type="password"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            )}
            {extra.length > 0 && (
              <div className={styles.grid}>
                {extra.slice(0, 12).map((c) => (
                  <CompanyCard
                    key={c.company_id}
                    c={c}
                    selected={selected?.company_id === c.company_id}
                    onSelect={() => choose(c)}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
