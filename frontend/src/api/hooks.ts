import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, isApiError, unwrap } from './client';
import type { AnalyzeInput, FeedbackIn, OverridesUpdate, Role } from './types';

export interface FeedFilters {
  direction?: 'risk' | 'opportunity' | 'mixed';
  min_impact?: 'low' | 'medium' | 'high' | 'critical';
}

const notRetry4xx = (count: number, error: unknown) =>
  !(isApiError(error) && error.status < 500) && count < 1;

export function useMeta() {
  return useQuery({
    queryKey: ['meta'],
    queryFn: async () => unwrap(await api.GET('/api/meta')),
    staleTime: 60_000,
  });
}

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: async () => unwrap(await api.GET('/api/session'), { allow401: true }),
    retry: false,
    staleTime: 30_000,
  });
}

export function useDemoCompanies(q?: string) {
  return useQuery({
    queryKey: ['companies', q ?? ''],
    queryFn: async () =>
      unwrap(await api.GET('/api/demo/companies', { params: { query: { q: q || undefined, limit: 30 } } })),
  });
}

export function useFeed(role: Role | undefined, filters: FeedFilters) {
  return useInfiniteQuery({
    queryKey: ['feed', role, filters],
    enabled: !!role,
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET('/api/feed', {
          params: { query: { limit: 20, cursor: pageParam ?? undefined, ...filters } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    refetchInterval: 60_000,
  });
}

export function useBrief(role: Role | undefined) {
  return useQuery({
    queryKey: ['brief', role],
    enabled: !!role,
    queryFn: async () => unwrap(await api.GET('/api/brief')),
  });
}

export function useInsight(id: string | undefined) {
  return useQuery({
    queryKey: ['insight', id],
    enabled: !!id,
    retry: notRetry4xx,
    queryFn: async () =>
      unwrap(await api.GET('/api/insights/{insight_id}', { params: { path: { insight_id: id! } } })),
  });
}

export function useTrace(id: string | undefined) {
  return useQuery({
    queryKey: ['trace', id],
    enabled: !!id,
    queryFn: async () =>
      unwrap(await api.GET('/api/insights/{insight_id}/trace', { params: { path: { insight_id: id! } } })),
  });
}

export function useProfile() {
  return useQuery({ queryKey: ['profile'], queryFn: async () => unwrap(await api.GET('/api/me/profile')) });
}

export function useCounterparties(direction: 'suppliers' | 'buyers', industryId?: string, limit = 10) {
  return useQuery({
    queryKey: ['counterparties', direction, industryId ?? null, limit],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/me/counterparties', {
          params: { query: { direction, industry_id: industryId, limit } },
        }),
      ),
  });
}

export function useReference() {
  return useQuery({
    queryKey: ['reference'],
    queryFn: async () => unwrap(await api.GET('/api/reference')),
    staleTime: Infinity,
  });
}

export function useSource(id: string | null) {
  return useQuery({
    queryKey: ['source', id],
    enabled: !!id,
    queryFn: async () =>
      unwrap(await api.GET('/api/sources/{source_id}', { params: { path: { source_id: id! } } })),
  });
}

export function useChat(insightId: string | undefined, threadId: string | null) {
  return useQuery({
    queryKey: ['chat', insightId, threadId],
    enabled: !!insightId,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/insights/{insight_id}/chat', {
          params: { path: { insight_id: insightId! }, query: { thread_id: threadId ?? undefined } },
        }),
      ),
  });
}

export function useAnalyzeHistory() {
  return useQuery({
    queryKey: ['analyzeHistory'],
    queryFn: async () => unwrap(await api.GET('/api/analyze/history')),
  });
}

export function useMacro() {
  return useQuery({
    queryKey: ['macro'],
    queryFn: async () => unwrap(await api.GET('/api/macro')),
    staleTime: 300_000,
  });
}

export function useQuality() {
  return useQuery({ queryKey: ['quality'], queryFn: async () => unwrap(await api.GET('/api/quality')) });
}

export function useRun(runId: string | null) {
  return useQuery({
    queryKey: ['run', runId],
    enabled: !!runId,
    queryFn: async () =>
      unwrap(await api.GET('/api/runs/{run_id}', { params: { path: { run_id: runId! } } })),
  });
}

// ── мутации ──
export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { company_id: string; role: Role; jury_code?: string | null }) =>
      unwrap(await api.POST('/api/session', { body }), { allow401: true }),
    onSuccess: (data) => {
      qc.clear();
      qc.setQueryData(['session'], data);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.DELETE('/api/session');
    },
    onSuccess: () => qc.clear(),
  });
}

export function useChangeRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (role: Role) => unwrap(await api.PATCH('/api/session', { body: { role } })),
    onSuccess: (data) => {
      qc.setQueryData(['session'], data);
      void qc.invalidateQueries({ queryKey: ['feed'] });
      void qc.invalidateQueries({ queryKey: ['brief'] });
    },
  });
}

export function useGenerateInsight() {
  return useMutation({
    mutationFn: async (eventId: number) =>
      unwrap(await api.POST('/api/events/{event_id}/insight', { params: { path: { event_id: eventId } } })),
  });
}

export function useAnalyze() {
  return useMutation({
    mutationFn: async (body: AnalyzeInput) => unwrap(await api.POST('/api/analyze', { body })),
  });
}

export function useSendChat(insightId: string) {
  return useMutation({
    mutationFn: async (body: { message: string; thread_id?: string | null }) =>
      unwrap(
        await api.POST('/api/insights/{insight_id}/chat', {
          params: { path: { insight_id: insightId } },
          body,
        }),
      ),
  });
}

export function useFeedback(insightId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: FeedbackIn) =>
      unwrap(
        await api.POST('/api/insights/{insight_id}/feedback', {
          params: { path: { insight_id: insightId } },
          body,
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['insight', insightId] }),
  });
}

export function useSaveOverrides() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: OverridesUpdate) => unwrap(await api.PUT('/api/me/profile/overrides', { body })),
    onSuccess: (data) => {
      qc.setQueryData(['profile'], data);
      void qc.invalidateQueries({ queryKey: ['feed'] });
      void qc.invalidateQueries({ queryKey: ['brief'] });
      void qc.invalidateQueries({ queryKey: ['counterparties'] });
    },
  });
}

export function useCreateLead() {
  return useMutation({
    mutationFn: async (body: { product_id: string; insight_id?: string | null; comment?: string | null }) =>
      unwrap(await api.POST('/api/leads', { body: { ...body, confirm: true } })),
  });
}
