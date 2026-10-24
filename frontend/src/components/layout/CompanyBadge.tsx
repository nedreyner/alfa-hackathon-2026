import { useSession } from '../../api/hooks';

export function CompanyBadge() {
  const session = useSession();
  const c = session.data?.company;
  if (!c) return null;
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {c.name}
      </div>
      <div className="caption" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {c.industry_name}
      </div>
    </div>
  );
}
