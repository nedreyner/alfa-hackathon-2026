import { Button } from '@alfalab/core-components/button';
import { useState } from 'react';

import { useCreateLead, useReference } from '../../api/hooks';
import type { ProductOffer } from '../../api/types';
import { Panel } from '../common/Panel';

export function LeadModal({
  product,
  insightId,
  onClose,
}: {
  product: ProductOffer | null;
  insightId: string;
  onClose: () => void;
}) {
  const ref = useReference();
  const lead = useCreateLead();
  const [comment, setComment] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  return (
    <Panel
      open={!!product}
      onClose={() => {
        lead.reset();
        setConfirmed(false);
        onClose();
      }}
      title={product ? `Альфа-Банк: ${product.name}` : ''}
    >
      {product && (
        <div className="stack" style={{ paddingBottom: 24 }}>
          <p style={{ margin: 0, fontSize: 17 }}>{product.pitch}</p>
          <p className="caption" style={{ margin: 0 }}>
            {ref.data?.products_disclaimer}
          </p>
          {lead.isSuccess ? (
            <div className="card" role="status" style={{ boxShadow: 'none' }}>
              {lead.data.message}
            </div>
          ) : (
            <>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                maxLength={500}
                rows={3}
                placeholder="Комментарий для менеджера (необязательно)"
                style={{
                  padding: 12,
                  borderRadius: 12,
                  border: '1px solid var(--ai-border)',
                  font: 'inherit',
                  resize: 'vertical',
                }}
              />
              <label className="row secondary" style={{ cursor: 'pointer' }}>
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                Подтверждаю, что хочу оставить заявку (демо)
              </label>
              <Button
                view="accent"
                size={48}
                disabled={!confirmed}
                loading={lead.isPending}
                onClick={() =>
                  lead.mutate({
                    product_id: product.product_id,
                    insight_id: insightId,
                    comment: comment || null,
                  })
                }
              >
                Оставить заявку (демо)
              </Button>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}
