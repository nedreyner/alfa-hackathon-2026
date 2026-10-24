import { Button } from '@alfalab/core-components/button';
import type { ReactNode } from 'react';

import { errorMessage } from '../../lib/errors';

export function ErrorState({
  error,
  onRetry,
  children,
}: {
  error?: unknown;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="card" role="alert" style={{ padding: '28px 24px' }}>
      <div className="h2">{children ?? errorMessage(error)}</div>
      {onRetry && (
        <Button view="secondary" size={40} onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  );
}
