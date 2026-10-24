import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ReviewItem } from '../../api/types';
import { renderWithProviders } from '../../test/render';
import { ReviewQueue } from './ReviewQueue';

const mutate = vi.fn();
const items: ReviewItem[] = [
  {
    insight_id: 'ins_1',
    company_id: 'SYN-DEMO-02',
    event_id: 1,
    headline: 'Арматура дорожает',
    status: 'needs_review',
    confidence_level: 'low',
    supported_share: 0.5,
    removed_claims: 2,
    created_at: '2026-10-24T00:00:00Z',
    review_note: null,
  },
];
vi.mock('../../api/hooks', () => ({
  adminToken: () => null,
  setAdminToken: vi.fn(),
  useReviewQueue: (enabled: boolean) => ({ data: enabled ? items : undefined, isError: false }),
  useReview: () => ({ mutate, isPending: false, variables: undefined }),
}));

describe('ReviewQueue', () => {
  it('ordinary session sees only the expert entry', () => {
    renderWithProviders(<ReviewQueue jury={false} companyId="SYN-DEMO-02" />);
    expect(screen.queryByText('Арматура дорожает')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Режим эксперта' }));
    expect(screen.getByPlaceholderText('Токен администратора')).toBeTruthy();
  });

  it('jury approves and rejects', () => {
    renderWithProviders(<ReviewQueue jury companyId="SYN-DEMO-02" />);
    expect(screen.getByRole('link', { name: 'Арматура дорожает' }).getAttribute('href')).toBe(
      '/insights/ins_1',
    );
    expect(screen.getByText(/скрыто выводов: 2/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Утвердить' }));
    expect(mutate).toHaveBeenCalledWith({ insightId: 'ins_1', status: 'published' });
    fireEvent.click(screen.getByRole('button', { name: 'Отклонить' }));
    expect(mutate).toHaveBeenLastCalledWith({ insightId: 'ins_1', status: 'rejected' });
  });
});
