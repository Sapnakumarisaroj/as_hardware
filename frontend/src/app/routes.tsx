import type { RouteObject } from 'react-router'

import { CategoryPage } from '@/pages/CategoryPage'
import { HomePage } from '@/pages/HomePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProductDetailPage } from '@/pages/ProductDetailPage'
import { RouteErrorPage } from '@/pages/RouteErrorPage'
import { SearchPage } from '@/pages/SearchPage'

import { AppProviders } from './AppProviders'
import { CustomerLayout } from './layouts/CustomerLayout'
import { RiderLayout } from './layouts/RiderLayout'

/* Cart, checkout, auth and account pages load on demand, so browsing the catalogue doesn't download them. */
const account = () => import('@/pages/AccountPages')
const auth = () => import('@/pages/AuthPages')
const rider = () => import('@/pages/RiderPages')

/**
 * Route table. Readable slug URLs: /c/<category-slug>, /p/<product-slug>.
 * /rider/* is the delivery partner app. The admin shell (/admin/*) is added in a later phase.
 */
export const routes: RouteObject[] = [
  {
    element: <AppProviders />,
    children: [
      {
        element: <CustomerLayout />,
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, element: <HomePage /> },
          { path: 'products', element: <SearchPage mode="all" /> },
          { path: 'search', element: <SearchPage mode="search" /> },
          { path: 'c/:slug', element: <CategoryPage /> },
          { path: 'p/:slug', element: <ProductDetailPage /> },
          { path: 'cart', lazy: async () => ({ Component: (await import('@/pages/CartPage')).CartPage }) },
          { path: 'checkout', lazy: async () => ({ Component: (await import('@/pages/CheckoutPage')).CheckoutPage }) },
          { path: 'orders/:number/pay', lazy: async () => ({ Component: (await import('@/pages/PaymentPage')).PaymentPage }) },
          {
            path: 'order-confirmation/:number',
            lazy: async () => ({ Component: (await import('@/pages/OrderConfirmationPage')).OrderConfirmationPage }),
          },
          { path: 'wishlist', lazy: async () => ({ Component: (await import('@/pages/WishlistPage')).WishlistPage }) },
          { path: 'login', lazy: async () => ({ Component: (await auth()).LoginPage }) },
          { path: 'register', lazy: async () => ({ Component: (await auth()).RegisterPage }) },
          { path: 'account', lazy: async () => ({ Component: (await account()).AccountPage }) },
          { path: 'account/orders', lazy: async () => ({ Component: (await account()).OrdersPage }) },
          { path: 'account/orders/:number', lazy: async () => ({ Component: (await account()).OrderDetailPage }) },
          { path: 'account/addresses', lazy: async () => ({ Component: (await account()).AddressesPage }) },
          { path: 'account/returns', lazy: async () => ({ Component: (await account()).ReturnsPage }) },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
      {
        // Delivery partners (Phase 10). The API checks the role on every request; this shell only shows it.
        path: 'rider',
        element: <RiderLayout />,
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, lazy: async () => ({ Component: (await rider()).RiderDashboardPage }) },
          { path: 'history', lazy: async () => ({ Component: (await rider()).RiderHistoryPage }) },
          { path: 'jobs/:id', lazy: async () => ({ Component: (await rider()).RiderJobPage }) },
        ],
      },
    ],
  },
]
