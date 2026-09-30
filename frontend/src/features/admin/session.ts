import { useOutletContext } from 'react-router'

import type { AdminSession } from './types'

/** Who is using the dashboard and what they may do (loaded once by AdminLayout). */
export function useSession(): AdminSession {
  return useOutletContext<AdminSession>()
}
