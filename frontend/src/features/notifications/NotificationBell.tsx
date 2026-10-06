import { Link } from 'react-router'

import { BellIcon } from '@/components/icons'

import { useUnreadCount } from './api'

/** Header bell: opens the inbox and shows how many messages are unread (signed-in people only). */
export function NotificationBell({ tone = 'dark', className = '' }: { tone?: 'dark' | 'light'; className?: string }) {
  const unread = useUnreadCount().data?.unread ?? 0
  const hover = tone === 'dark' ? 'hover:text-amber-500' : 'rounded-md p-2 hover:bg-steel-100'
  return (
    <Link
      to="/notifications"
      className={`relative ${hover} ${className}`}
      aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
    >
      <BellIcon className="size-6" />
      {unread > 0 && (
        <span
          aria-hidden
          className="absolute -right-1.5 -top-1.5 grid min-w-5 place-items-center rounded-full bg-amber-500 px-1 text-[11px] font-bold leading-5 text-ink-950"
        >
          {unread > 99 ? '99+' : unread}
        </span>
      )}
    </Link>
  )
}
