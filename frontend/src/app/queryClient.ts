import { QueryClient } from '@tanstack/react-query';

import { isApiError } from '../api/client';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, error) => !(isApiError(error) && error.status < 500) && count < 1,
        refetchOnWindowFocus: false,
        staleTime: 15_000,
      },
    },
  });
}
