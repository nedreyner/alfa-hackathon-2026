import { SegmentedControl, Segment } from '@alfalab/core-components/segmented-control';

import { useChangeRole, useSession } from '../../api/hooks';
import type { Role } from '../../api/types';
import { ROLE, ROLE_SHORT } from '../../lib/labels';

const ROLES: Role[] = ['cfo', 'treasurer', 'owner'];

export function RoleSwitcher({ compact = false }: { compact?: boolean }) {
  const session = useSession();
  const change = useChangeRole();
  const role = session.data?.role;
  if (!role) return null;
  return (
    <div aria-label="Роль читателя">
      <SegmentedControl
        size={32}
        selectedId={role}
        onChange={(id) => {
          if (id !== role) change.mutate(id as Role);
        }}
        disabled={change.isPending}
      >
        {ROLES.map((r) => (
          <Segment key={r} id={r} title={compact ? ROLE_SHORT[r] : ROLE[r]} />
        ))}
      </SegmentedControl>
    </div>
  );
}
