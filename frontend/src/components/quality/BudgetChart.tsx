import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const TASK_COLORS: Record<string, string> = {
  tagging: '#0e0e10',
  draft: '#ef3124',
  verify: '#7a7a80',
  revise: '#f29b94',
  agent: '#4a4a50',
  chat: '#a5a5ab',
  ocr: '#c7c7cc',
  research_extract: '#dcdce0',
  tagging_interactive: '#2b2b30',
};
const TASK_RU: Record<string, string> = {
  tagging: 'разметка',
  tagging_interactive: 'разметка (B)',
  draft: 'черновик',
  verify: 'проверка',
  revise: 'доработка',
  agent: 'агент',
  chat: 'чат',
  ocr: 'OCR',
  research_extract: 'аналитика',
};

export default function BudgetChart({ days }: { days: { day: string; by_task: Record<string, number> }[] }) {
  const tasks = [...new Set(days.flatMap((d) => Object.keys(d.by_task)))];
  const data = [...days].reverse().map((d) => ({ day: d.day.slice(5), ...d.by_task }));
  return (
    <div style={{ width: '100%', height: 260 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="#e7e8eb" />
          <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={12} />
          <YAxis tickLine={false} axisLine={false} fontSize={12} unit=" ₽" />
          <Tooltip
            formatter={(v, name) => [`${Number(v).toFixed(2)} ₽`, TASK_RU[String(name)] ?? String(name)]}
          />
          <Legend
            formatter={(name) => (
              <span style={{ color: '#4d4d4d' }}>{TASK_RU[String(name)] ?? String(name)}</span>
            )}
            wrapperStyle={{ fontSize: 12 }}
          />
          {tasks.map((t) => (
            <Bar key={t} dataKey={t} stackId="a" fill={TASK_COLORS[t] ?? '#999'} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
