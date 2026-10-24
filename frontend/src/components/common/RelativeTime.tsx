import { formatDate, formatRelative } from '../../lib/format';

export function RelativeTime({ value }: { value: string }) {
  return (
    <time dateTime={value} title={formatDate(value)}>
      {formatRelative(value)}
    </time>
  );
}
