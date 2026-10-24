import { ContentResponsive, HeaderResponsive, SidePanel } from '@alfalab/core-components/side-panel';
import type { ReactNode } from 'react';

/** Боковая панель Альфы: на мобильных — во весь экран. */
export function Panel({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  return (
    <SidePanel open={open} onClose={onClose} size={500} hasCloser>
      <HeaderResponsive title={title} hasCloser />
      <ContentResponsive>{children}</ContentResponsive>
    </SidePanel>
  );
}
