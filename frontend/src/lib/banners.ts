import { BUDGET_MODE } from './labels';

export interface Banner {
  key: string;
  text: string;
  tone: 'info' | 'warn';
}

export function banners(meta?: {
  demo_mode: boolean;
  llm_mode: string;
  budget_mode: string;
  data_profile: string;
}): Banner[] {
  if (!meta) return [];
  const out: Banner[] = [];
  if (meta.llm_mode === 'fake')
    out.push({ key: 'fake', tone: 'warn', text: 'Тестовый режим: ответы ИИ сгенерированы заглушкой' });
  if (meta.llm_mode === 'replay')
    out.push({ key: 'replay', tone: 'info', text: 'Демо из сохранённых ответов: новые разборы недоступны' });
  if (meta.budget_mode !== 'normal')
    out.push({
      key: `budget-${meta.budget_mode}`,
      tone: 'warn',
      text: BUDGET_MODE[meta.budget_mode as keyof typeof BUDGET_MODE],
    });
  if (meta.demo_mode)
    out.push({
      key: 'demo',
      tone: 'info',
      text: meta.data_profile === 'synthetic' ? 'Демо-режим: синтетические данные компаний' : 'Демо-режим',
    });
  return out;
}
