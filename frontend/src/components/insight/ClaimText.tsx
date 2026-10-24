import type { Claim } from '../../api/types';
import { CLAIM_TYPE, CLAIM_TYPE_HINT, LEVEL } from '../../lib/labels';
import styles from './claims.module.css';
import { useSourceDrawer } from './sourceContext';

export function ClaimLabel({ claim }: { claim: Claim }) {
  const hint =
    claim.type === 'ai' && claim.confidence
      ? `${CLAIM_TYPE_HINT.ai}. Уверенность: ${LEVEL[claim.confidence]}`
      : CLAIM_TYPE_HINT[claim.type];
  return (
    <span className={`${styles.label} ${styles[claim.type]}`} title={hint}>
      {CLAIM_TYPE[claim.type]}
    </span>
  );
}

/** Утверждение с бейджем происхождения; клик открывает источники из refs. */
export function ClaimText({ claim }: { claim: Claim }) {
  const drawer = useSourceDrawer();
  const refs = claim.refs ?? [];
  const open = () => refs.length && drawer.open(refs, 'Источники утверждения');
  return (
    <span>
      <span
        className={`${styles.claim} ${refs.length ? '' : styles.noRefs}`}
        role={refs.length ? 'button' : undefined}
        tabIndex={refs.length ? 0 : undefined}
        onClick={open}
        onKeyDown={(e) => e.key === 'Enter' && open()}
        title={refs.length ? 'Показать источники' : undefined}
      >
        {claim.text}
      </span>
      <ClaimLabel claim={claim} />
    </span>
  );
}
