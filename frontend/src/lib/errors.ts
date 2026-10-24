import { isApiError } from '../api/client';

export function errorMessage(error: unknown): string {
  if (isApiError(error)) return error.message;
  return 'Не удалось загрузить данные';
}
