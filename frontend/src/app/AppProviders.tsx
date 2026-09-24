import { Outlet } from 'react-router'

import { ToastProvider } from '@/components/toast'
import { AuthProvider } from '@/features/auth/AuthProvider'
import { PendingActionRunner } from '@/features/auth/PendingActionRunner'

/** Root route element: app-wide providers that need the router (toasts render <Link>s). */
export function AppProviders() {
  return (
    <ToastProvider>
      <AuthProvider>
        <PendingActionRunner />
        <Outlet />
      </AuthProvider>
    </ToastProvider>
  )
}
