import type { ReactNode } from 'react';

export function EmptyState({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="card" style={{ textAlign: 'center', padding: '40px 24px' }}>
      <div className="h2">{title}</div>
      {text && (
        <p className="secondary" style={{ margin: '0 0 16px' }}>
          {text}
        </p>
      )}
      {action}
    </div>
  );
}
