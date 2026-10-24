import type { Direction, ImpactLevel, Level } from '../../api/types';
import { DIRECTION, IMPACT, IMPACT_DOTS, LEVEL } from '../../lib/labels';
import styles from './badges.module.css';

export function DirectionTag({ direction }: { direction: Direction }) {
  return <span className={`${styles.tag} ${styles[direction]}`}>{DIRECTION[direction]}</span>;
}

export function ImpactBadge({ level }: { level: ImpactLevel }) {
  const n = IMPACT_DOTS[level];
  return (
    <span className={styles.meta} title={`Влияние: ${IMPACT[level]}`}>
      <span className={styles.dots} aria-hidden="true">
        {[1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={`${styles.dot} ${i <= n ? (level === 'critical' ? styles.dotCritical : styles.dotOn) : ''}`}
          />
        ))}
      </span>
      Влияние: {IMPACT[level]}
    </span>
  );
}

export function ConfidenceBadge({ level, reasons }: { level: Level; reasons?: string[] }) {
  return (
    <span className={styles.meta} title={reasons?.join('\n')}>
      Уверенность: {LEVEL[level]}
    </span>
  );
}

export function WarnPlate({ children }: { children: string }) {
  return <span className={`${styles.small} ${styles.warnPlate}`}>{children}</span>;
}
