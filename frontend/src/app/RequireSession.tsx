import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router';

import { useSession } from '../api/hooks';
import { SkeletonCard } from '../components/common/SkeletonCard';

export function RequireSession({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session.isPending) {
    return (
      <div className="page">
        <SkeletonCard />
      </div>
    );
  }
  if (session.isError || !session.data)
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}
