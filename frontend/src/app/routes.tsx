import type { RouteObject } from 'react-router'

import { AccountPage, OrdersPage } from '@/pages/AccountPages'
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
          { path: 'wishlist', element: <WishlistPage /> },
          { path: 'login', element: <LoginPage /> },
          { path: 'register', element: <RegisterPage /> },
          { path: 'account', element: <AccountPage /> },
          { path: 'account/orders', element: <OrdersPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
