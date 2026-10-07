import type { RouteObject } from 'react-router'

import { HomePage } from '@/pages/HomePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { RouteErrorPage } from '@/pages/RouteErrorPage'

import { AppProviders } from './AppProviders'
import { CustomerLayout } from './layouts/CustomerLayout'
import { RiderLayout } from './layouts/RiderLayout'

/* Cart, checkout, auth and account pages load on demand, so browsing the catalogue doesn't download them. */
const account = () => import('@/pages/AccountPages')
const auth = () => import('@/pages/AuthPages')
const rider = () => import('@/pages/RiderPages')
const overview = () => import('@/pages/admin/OverviewPages')
const adminOrders = () => import('@/pages/admin/OrderPages')
const catalog = () => import('@/pages/admin/CatalogPages')
const stores = () => import('@/pages/admin/StorePages')
const offers = () => import('@/pages/admin/OfferPages')
const customers = () => import('@/pages/admin/CustomerPages')
const returns = () => import('@/pages/admin/ReturnRefundPages')
const support = () => import('@/pages/admin/SupportPages')
const commerce = () => import('@/pages/admin/CommercePages')
const shoppingAdmin = () => import('@/pages/admin/ShoppingAdminPages')
const notificationsAdmin = () => import('@/pages/admin/NotificationPages')
const reportPages = () => import('@/pages/admin/ReportPages')
const brands = () => import('@/pages/BrandPages')
const projects = () => import('@/pages/ProjectPages')
const shopping = () => import('@/pages/ShoppingPages')
// Listing and product pages are split from the home page bundle (Phase 16); each loads on first visit.
const search = () => import('@/pages/SearchPage')

/**
 * Route table. Readable slug URLs: /c/<category-slug>, /p/<product-slug>, /brand/<brand-slug>.
 * /rider/* is the delivery partner app, /admin/* the business dashboard.
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
          {
            path: 'products',
            lazy: async () => {
              const { SearchPage } = await search()
              return { Component: () => <SearchPage mode="all" /> }
            },
          },
          {
            path: 'search',
            lazy: async () => {
              const { SearchPage } = await search()
              return { Component: () => <SearchPage mode="search" /> }
            },
          },
          { path: 'c/:slug', lazy: async () => ({ Component: (await import('@/pages/CategoryPage')).CategoryPage }) },
          { path: 'p/:slug', lazy: async () => ({ Component: (await import('@/pages/ProductDetailPage')).ProductDetailPage }) },
          { path: 'brands', lazy: async () => ({ Component: (await brands()).BrandsPage }) },
          { path: 'brand/:slug', lazy: async () => ({ Component: (await brands()).BrandPage }) },
          { path: 'cart', lazy: async () => ({ Component: (await import('@/pages/CartPage')).CartPage }) },
          { path: 'checkout', lazy: async () => ({ Component: (await import('@/pages/CheckoutPage')).CheckoutPage }) },
          { path: 'orders/:number/pay', lazy: async () => ({ Component: (await import('@/pages/PaymentPage')).PaymentPage }) },
          {
            path: 'order-confirmation/:number',
            lazy: async () => ({ Component: (await import('@/pages/OrderConfirmationPage')).OrderConfirmationPage }),
          },
          { path: 'wishlist', lazy: async () => ({ Component: (await import('@/pages/WishlistPage')).WishlistPage }) },
          { path: 'ai-assistant', lazy: async () => ({ Component: (await import('@/pages/AssistantPage')).AssistantPage }) },
          {
            path: 'image-search',
            lazy: async () => ({ Component: (await import('@/pages/ImageSearchPage')).ImageSearchPage }),
          },
          { path: 'budget', lazy: async () => ({ Component: (await shopping()).BudgetPage }) },
          { path: 'bundles', lazy: async () => ({ Component: (await shopping()).BundlesPage }) },
          { path: 'bundles/:slug', lazy: async () => ({ Component: (await shopping()).BundlePage }) },
          { path: 'quantity', lazy: async () => ({ Component: (await import('@/pages/QuantityPage')).QuantityPage }) },
          { path: 'projects', lazy: async () => ({ Component: (await projects()).ProjectsPage }) },
          { path: 'projects/:id', lazy: async () => ({ Component: (await projects()).ProjectPage }) },
          { path: 'voice', lazy: async () => ({ Component: (await import('@/pages/VoicePage')).VoicePage }) },
          { path: 'login', lazy: async () => ({ Component: (await auth()).LoginPage }) },
          { path: 'register', lazy: async () => ({ Component: (await auth()).RegisterPage }) },
          { path: 'account', lazy: async () => ({ Component: (await account()).AccountPage }) },
          { path: 'account/orders', lazy: async () => ({ Component: (await account()).OrdersPage }) },
          { path: 'account/orders/:number', lazy: async () => ({ Component: (await account()).OrderDetailPage }) },
          { path: 'account/addresses', lazy: async () => ({ Component: (await account()).AddressesPage }) },
          { path: 'account/returns', lazy: async () => ({ Component: (await account()).ReturnsPage }) },
          { path: 'notifications', lazy: async () => ({ Component: (await import('@/pages/NotificationsPage')).NotificationsPage }) },
          { path: 'account/wallet', lazy: async () => ({ Component: (await import('@/pages/WalletPage')).WalletPage }) },
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
      {
        // The business dashboard (Phase 11) for administrators and store managers. Nothing of it is
        // in the customer bundle: the shell and every section load on demand. The API checks the
        // role and the store on every request; this shell only shows what the role may use.
        path: 'admin',
        lazy: async () => ({ Component: (await import('./layouts/AdminLayout')).AdminLayout }),
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, lazy: async () => ({ Component: (await overview()).AdminDashboardPage }) },
          { path: 'analytics', lazy: async () => ({ Component: (await overview()).AdminAnalyticsPage }) },
          { path: 'reports', lazy: async () => ({ Component: (await reportPages()).AdminReportsPage }) },
          { path: 'assistant', lazy: async () => ({ Component: (await reportPages()).AdminAssistantPage }) },
          { path: 'orders', lazy: async () => ({ Component: (await adminOrders()).AdminOrdersPage }) },
          { path: 'orders/:number', lazy: async () => ({ Component: (await adminOrders()).AdminOrderDetailPage }) },
          { path: 'products', lazy: async () => ({ Component: (await catalog()).AdminProductsPage }) },
          { path: 'products/:id', lazy: async () => ({ Component: (await catalog()).AdminProductPage }) },
          { path: 'categories', lazy: async () => ({ Component: (await catalog()).AdminCategoriesPage }) },
          { path: 'brands', lazy: async () => ({ Component: (await catalog()).AdminBrandsPage }) },
          {
            path: 'inventory',
            lazy: async () => ({ Component: (await import('@/pages/admin/InventoryPage')).AdminInventoryPage }),
          },
          { path: 'stores', lazy: async () => ({ Component: (await stores()).AdminStoresListPage }) },
          { path: 'stores/:id', lazy: async () => ({ Component: (await stores()).AdminStoreDetailPage }) },
          { path: 'warehouses', lazy: async () => ({ Component: (await stores()).AdminWarehousesListPage }) },
          { path: 'warehouses/:id', lazy: async () => ({ Component: (await stores()).AdminWarehouseDetailPage }) },
          {
            path: 'delivery',
            lazy: async () => ({ Component: (await import('@/pages/admin/DeliveryPage')).AdminDeliveryPage }),
          },
          { path: 'offers', lazy: async () => ({ Component: (await offers()).AdminOffersPage }) },
          { path: 'coupons', lazy: async () => ({ Component: (await offers()).AdminCouponsPage }) },
          { path: 'options', lazy: async () => ({ Component: (await commerce()).AdminOptionTypesPage }) },
          { path: 'collections', lazy: async () => ({ Component: (await commerce()).AdminCollectionsPage }) },
          { path: 'bundles', lazy: async () => ({ Component: (await shoppingAdmin()).AdminBundlesPage }) },
          { path: 'recommendations', lazy: async () => ({ Component: (await shoppingAdmin()).AdminRecommendationRulesPage }) },
          { path: 'free-delivery', lazy: async () => ({ Component: (await commerce()).AdminFreeDeliveryPage }) },
          { path: 'payment-settings', lazy: async () => ({ Component: (await commerce()).AdminPaymentSettingsPage }) },
          {
            path: 'loyalty',
            lazy: async () => ({ Component: (await import('@/pages/admin/LoyaltyPages')).AdminLoyaltyPage }),
          },
          { path: 'customers', lazy: async () => ({ Component: (await customers()).AdminCustomersPage }) },
          { path: 'customers/:id', lazy: async () => ({ Component: (await customers()).AdminCustomerPage }) },
          { path: 'returns', lazy: async () => ({ Component: (await returns()).AdminReturnsPage }) },
          { path: 'refunds', lazy: async () => ({ Component: (await returns()).AdminRefundsPage }) },
          { path: 'support', lazy: async () => ({ Component: (await support()).AdminSupportPage }) },
          { path: 'notifications', lazy: async () => ({ Component: (await notificationsAdmin()).AdminNotificationsPage }) },
          { path: 'support/:id', lazy: async () => ({ Component: (await support()).AdminConversationPage }) },
          {
            path: 'search',
            lazy: async () => ({ Component: (await import('@/pages/admin/SearchPage')).AdminSearchPage }),
          },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
