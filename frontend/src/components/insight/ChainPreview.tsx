export function ChainPreview({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  const parts = text.split(' → ');
  return (
    <div
      title={text}
      style={{
        fontSize: 14,
        lineHeight: '20px',
        color: 'var(--ai-text-secondary)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && (
            <span aria-hidden="true" style={{ color: 'var(--ai-accent)', margin: '0 6px' }}>
              →
            </span>
          )}
          {p}
        </span>
      ))}
    </div>
  );
}
