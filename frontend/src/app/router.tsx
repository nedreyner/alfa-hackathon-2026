/* eslint-disable react-refresh/only-export-components -- модуль маршрутов: lazy-страницы и конфигурация */
import { lazy, Suspense, type ReactNode } from 'react';
import { createBrowserRouter } from 'react-router';

import { AppShell } from '../components/layout/AppShell';
import { SkeletonCard } from '../components/common/SkeletonCard';
import { RequireSession } from './RequireSession';

const LoginPage = lazy(() => import('../pages/LoginPage'));
const HomePage = lazy(() => import('../pages/HomePage'));
const FeedPage = lazy(() => import('../pages/FeedPage'));
const InsightPage = lazy(() => import('../pages/InsightPage'));
const TracePage = lazy(() => import('../pages/TracePage'));
const AnalyzePage = lazy(() => import('../pages/AnalyzePage'));
const ProfilePage = lazy(() => import('../pages/ProfilePage'));
const QualityPage = lazy(() => import('../pages/QualityPage'));
const NotFoundPage = lazy(() => import('../pages/NotFoundPage'));

function Lazy({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="page">
          <SkeletonCard />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

function Protected({ children }: { children: ReactNode }) {
  return (
    <RequireSession>
      <AppShell>
        <Lazy>{children}</Lazy>
      </AppShell>
    </RequireSession>
  );
}

export const routes = [
  {
    path: '/login',
    element: (
      <Lazy>
        <LoginPage />
      </Lazy>
    ),
  },
  {
    path: '/',
    element: (
      <Protected>
        <HomePage />
      </Protected>
    ),
  },
  {
    path: '/feed',
    element: (
      <Protected>
        <FeedPage />
      </Protected>
    ),
  },
  {
    path: '/insights/:insightId',
    element: (
      <Protected>
        <InsightPage />
      </Protected>
    ),
  },
  {
    path: '/insights/:insightId/trace',
    element: (
      <Protected>
        <TracePage />
      </Protected>
    ),
  },
  {
    path: '/analyze',
    element: (
      <Protected>
        <AnalyzePage />
      </Protected>
    ),
  },
  {
    path: '/profile',
    element: (
      <Protected>
        <ProfilePage />
      </Protected>
    ),
  },
  {
    path: '/quality',
    element: (
      <Protected>
        <QualityPage />
      </Protected>
    ),
  },
  {
    path: '*',
    element: (
      <Lazy>
        <NotFoundPage />
      </Lazy>
    ),
  },
];

export function createRouter() {
  return createBrowserRouter(routes);
}
