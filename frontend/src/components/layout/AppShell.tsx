import type { ReactNode } from 'react';

import { ModeBanner } from './ModeBanner';
import { TopBar } from './TopBar';

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <>
      <ModeBanner />
      <TopBar />
      <main id="main">{children}</main>
    </>
  );
}
