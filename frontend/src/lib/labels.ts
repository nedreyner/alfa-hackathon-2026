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
  cfo: 'Финдиректор',
  treasurer: 'Казначей',
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

/** Примеры для быстрого демо фичи B: тексты новостей (ссылки на разделы сайтов не разбираются как статьи). */
export const ANALYZE_EXAMPLES: { label: string; title: string; text: string }[] = [
  {
    label: 'Пошлины на прокат',
    title: 'Минпромторг предложил повысить ввозные пошлины на арматуру и прокат до 15%',
    text:
      'Минпромторг подготовил предложение о повышении ввозных пошлин на арматуру и плоский прокат из стран вне ЕАЭС до 15% с 1 января. ' +
      'По оценке министерства, мера поддержит загрузку российских металлургических заводов, которая снизилась на фоне падения внутреннего спроса. ' +
      'Участники рынка ожидают, что после введения пошлин цены на импортный металлопрокат вырастут на 8–10%, а российские производители ' +
      'смогут поднять отпускные цены. Строительные компании и металлотрейдеры, закупающие прокат в Китае, уже пересматривают контракты на первый квартал.',
  },
  {
    label: 'Ставка ЦБ',
    title: 'Банк России сохранил ключевую ставку на уровне 14%',
    text:
      'Совет директоров Банка России сохранил ключевую ставку на уровне 14% годовых. Регулятор отметил, что инфляционное давление остаётся повышенным, ' +
      'а кредитование компаний растёт быстрее ожиданий. Банк России допускает снижение ставки на ближайших заседаниях, если замедление инфляции ' +
      'окажется устойчивым. Аналитики ожидают, что стоимость кредитов для бизнеса и ставки по депозитам останутся высокими как минимум до конца квартала, ' +
      'а компании с плавающей ставкой по кредитам продолжат нести повышенную процентную нагрузку.',
  },
  {
    label: 'Курс юаня',
    title: 'Курс юаня обновил максимум с начала года',
    text:
      'Официальный курс юаня, установленный Банком России, вырос до максимума с начала года. Ослабление рубля связано с сокращением продаж валютной выручки ' +
      'экспортёрами и ростом спроса импортёров на юани перед новогодним сезоном закупок. По оценкам аналитиков, удорожание юаня на 5% повышает ' +
      'себестоимость импортных товаров из Китая — оборудования, автомобилей, комплектующих и химической продукции. Компании, закупающие товары в Китае, ' +
      'начали чаще фиксировать курс по будущим платежам с помощью форвардов.',
  },
];

export const CHAT_SUGGESTIONS = [
  'Что если ставка снизится до 12%?',
  'Покажи контрагентов в этой отрасли',
  'Где первоисточник?',
];

/** Страница «Качество»: офлайн-оценка (12-quality.md §5). */
export const RANKING_VARIANT: Record<string, string> = {
  ours: 'Альфа Инсайт: цепная реакция',
  no_payments: 'Без платёжных данных',
  industry_only: 'Только своя отрасль',
  random: 'Случайный порядок',
};
export const LABELS_SOURCE: Record<string, string> = {
  human: 'ручная разметка',
  llm: 'предразметка моделью, до ручной проверки',
  none: 'разметки нет',
};
