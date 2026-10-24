import type {
  Alignment,
  BudgetMode,
  ClaimType,
  Direction,
  FeedbackReason,
  Horizon,
  ImpactLevel,
  Level,
  Role,
  SourceKind,
  Urgency,
} from '../api/types';

export const DIRECTION: Record<Direction, string> = {
  risk: 'Риск',
  opportunity: 'Возможность',
  mixed: 'Смешанное влияние',
};

export const IMPACT: Record<ImpactLevel, string> = {
  low: 'низкое',
  medium: 'среднее',
  high: 'высокое',
  critical: 'критичное',
};
export const IMPACT_DOTS: Record<ImpactLevel, number> = { low: 1, medium: 2, high: 3, critical: 4 };

export const LEVEL: Record<Level, string> = { low: 'низкая', medium: 'средняя', high: 'высокая' };

export const CLAIM_TYPE: Record<ClaimType, string> = { fact: 'Факт', bank: 'Альфа-Банк', ai: 'Вывод ИИ' };
export const CLAIM_TYPE_HINT: Record<ClaimType, string> = {
  fact: 'Проверяемый факт из источника',
  bank: 'Позиция аналитиков Альфа-Банка',
  ai: 'Вывод модели на основе источников',
};

export const ROLE: Record<Role, string> = {
  cfo: 'Финансовый директор',
  treasurer: 'Казначей',
  owner: 'Собственник',
};
export const ROLE_SHORT: Record<Role, string> = {
  cfo: 'CFO',
  treasurer: 'Казначейство',
  owner: 'Собственник',
};
export const ROLE_FOR: Record<Role, string> = {
  cfo: 'для финдиректора',
  treasurer: 'для казначея',
  owner: 'для собственника',
};

export const URGENCY: Record<Urgency, string> = {
  now: 'сейчас',
  this_week: 'на этой неделе',
  this_month: 'в этом месяце',
  monitor: 'следить',
};

export const HORIZON: Record<Horizon, string> = {
  days: 'дни',
  weeks: 'недели',
  months: 'месяцы',
  quarters: 'кварталы',
};

export const SOURCE_KIND: Record<SourceKind, string> = {
  news: 'Новость',
  alfa: 'Аналитика Альфа-Банка',
  cbr: 'Данные ЦБ',
  client_data: 'Ваши данные',
  user_input: 'Ваш текст',
};

export const ALIGNMENT: Record<Alignment, string> = {
  supports: 'Согласуется с выводом',
  neutral: 'Нейтрально',
  contradicts: 'Расходится с выводом',
  no_data: 'Нет данных',
};

export const BUDGET_MODE: Record<BudgetMode, string> = {
  normal: 'Обычный режим',
  economy: 'Режим экономии: новые разборы готовятся медленнее',
  exhausted: 'Дневной лимит аналитики исчерпан — показываем готовые разборы',
};

export const FEEDBACK_REASON: Record<FeedbackReason, string> = {
  not_relevant: 'Не про нас',
  already_known: 'Уже знали',
  wrong_facts: 'Ошибка в фактах',
  too_generic: 'Слишком общо',
  unclear: 'Непонятно',
  useful_action: 'Полезное действие',
  useful_risk: 'Вовремя о риске',
  other: 'Другое',
};
export const NEGATIVE_REASONS: FeedbackReason[] = [
  'not_relevant',
  'already_known',
  'wrong_facts',
  'too_generic',
  'unclear',
  'other',
];
export const POSITIVE_REASONS: FeedbackReason[] = ['useful_action', 'useful_risk', 'other'];

/** Шесть вопросов кейса — заголовки секций карточки (08-agent.md §8.3). */
export const SECTIONS = {
  what: 'Что произошло',
  why: 'Почему это важно вам',
  risks: 'Риски',
  opportunities: 'Возможности',
  actions: 'Что можно сделать',
  bank: 'Позиция Альфа-Банка',
  sources: 'Источники',
} as const;

export type ErrorCode =
  | 'llm_unavailable'
  | 'budget_exhausted'
  | 'invalid_output'
  | 'fetch_failed'
  | 'unsupported_content'
  | 'blocked_url'
  | 'timeout'
  | 'interrupted'
  | 'internal'
  | 'connection_lost';

export const ERROR_TEXT: Record<ErrorCode, string> = {
  llm_unavailable: 'Сервис аналитики временно недоступен, попробуйте позже',
  budget_exhausted: 'Дневной лимит аналитики исчерпан, показываем готовые разборы',
  invalid_output: 'Не удалось подготовить разбор, попробуйте ещё раз',
  fetch_failed: 'Сайт не отдал страницу. Вставьте текст новости',
  unsupported_content: 'Не удалось извлечь текст статьи. Вставьте текст вручную',
  blocked_url: 'Этот адрес нельзя загрузить',
  timeout: 'Разбор занял слишком много времени, попробуйте ещё раз',
  interrupted: 'Разбор прерван, запустите заново',
  internal: 'Что-то пошло не так. Попробуйте ещё раз',
  connection_lost: 'Соединение потеряно. Обновите страницу',
};

export function errorText(code: string | null | undefined): string {
  return (code && (ERROR_TEXT as Record<string, string>)[code]) || ERROR_TEXT.internal;
}

export const PHASE: Record<string, string> = {
  intake: 'Приём новости',
  plan: 'План',
  tools: 'Сбор данных',
  draft: 'Черновик',
  verify: 'Проверка',
  revise: 'Доработка',
  finalize: 'Готово',
};

export const EVENT_TYPE_FALLBACK = 'Событие';

export const ANALYZE_EXAMPLES: { label: string; url: string }[] = [
  { label: 'Ключевая ставка ЦБ', url: 'https://www.cbr.ru/press/keypr/' },
  { label: 'Пошлины на металл', url: 'https://www.interfax.ru/business/' },
  { label: 'Курс юаня', url: 'https://www.rbc.ru/finances/' },
];

export const CHAT_SUGGESTIONS = [
  'Что если ставка снизится до 12%?',
  'Покажи контрагентов в этой отрасли',
  'Где первоисточник?',
];
