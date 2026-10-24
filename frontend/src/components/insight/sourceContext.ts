import { createContext, useContext } from 'react';

export interface SourceDrawerApi {
  open: (ids: string[], title?: string) => void;
}

export const SourceDrawerContext = createContext<SourceDrawerApi>({ open: () => undefined });

export function useSourceDrawer(): SourceDrawerApi {
  return useContext(SourceDrawerContext);
}
