import type { RouteObject } from 'react-router'

import { HomePage } from '@/pages/HomePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { RouteErrorPage } from '@/pages/RouteErrorPage'

import { CustomerLayout } from './layouts/CustomerLayout'

/**
 * Route table. Customer, admin (/admin/*) and delivery (/delivery/*) shells are
 * added phase by phase; only implemented routes are registered.
 */
export const routes: RouteObject[] = [
  {
    element: <CustomerLayout />,
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <HomePage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
