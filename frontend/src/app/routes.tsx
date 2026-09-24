import type { RouteObject } from 'react-router'

import { LoginPage, RegisterPage } from '@/pages/AuthPages'
import { CartPage } from '@/pages/CartPage'
import { CategoryPage } from '@/pages/CategoryPage'
import { HomePage } from '@/pages/HomePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProductDetailPage } from '@/pages/ProductDetailPage'
import { RouteErrorPage } from '@/pages/RouteErrorPage'
import { SearchPage } from '@/pages/SearchPage'
import { WishlistPage } from '@/pages/WishlistPage'

import { AppProviders } from './AppProviders'
import { CustomerLayout } from './layouts/CustomerLayout'

/* Checkout and account pages load on demand, so browsing the catalogue doesn't download them. */
const account = () => import('@/pages/AccountPages')

/**
 * Route table. Readable slug URLs: /c/<category-slug>, /p/<product-slug>.
 * Admin (/admin/*) and delivery (/delivery/*) shells are added in later phases.
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
          { path: 'cart', element: <CartPage /> },
          { path: 'checkout', lazy: async () => ({ Component: (await import('@/pages/CheckoutPage')).CheckoutPage }) },
          { path: 'orders/:number/pay', lazy: async () => ({ Component: (await import('@/pages/PaymentPage')).PaymentPage }) },
          {
            path: 'order-confirmation/:number',
            lazy: async () => ({ Component: (await import('@/pages/OrderConfirmationPage')).OrderConfirmationPage }),
          },
          { path: 'wishlist', element: <WishlistPage /> },
          { path: 'login', element: <LoginPage /> },
          { path: 'register', element: <RegisterPage /> },
          { path: 'account', lazy: async () => ({ Component: (await account()).AccountPage }) },
          { path: 'account/orders', lazy: async () => ({ Component: (await account()).OrdersPage }) },
          { path: 'account/orders/:number', lazy: async () => ({ Component: (await account()).OrderDetailPage }) },
          { path: 'account/addresses', lazy: async () => ({ Component: (await account()).AddressesPage }) },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
