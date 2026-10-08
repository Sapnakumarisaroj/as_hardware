import { useLocation, useNavigate } from 'react-router'

import { HeartIcon } from '@/components/icons'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { savePendingAction } from '@/features/auth/pendingAction'

import { useAddToWishlist, useRemoveFromWishlist, useWishlistIds } from './api'

interface Props {
  productId: number
  productName: string
  variant?: 'icon' | 'button'
}

export function WishlistButton({ productId, productName, variant = 'icon' }: Props) {
  const { status } = useAuth()
  const saved = useWishlistIds().has(productId)
  const add = useAddToWishlist()
  const remove = useRemoveFromWishlist()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const busy = add.isPending || remove.isPending

  function toggle() {
    if (status !== 'authenticated') {
      savePendingAction({ type: 'wishlist', productId, productName })
      toast.show('Login to save items — we’ll add this to your wishlist.', { tone: 'info' })
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
      return
    }
    const onError = () => toast.show('Could not update your wishlist. Please try again.', { tone: 'error' })
    if (saved) {
      remove.mutate(productId, { onSuccess: () => toast.show('Removed from wishlist'), onError })
    } else {
      add.mutate(productId, {
        onSuccess: () => toast.show('Saved to wishlist', { action: { label: 'View', to: '/wishlist' } }),
        onError,
      })
    }
  }

  const label = saved ? `Remove ${productName} from wishlist` : `Save ${productName} to wishlist`
  if (variant === 'button') {
    return (
      <button type="button" onClick={toggle} disabled={busy} aria-pressed={saved} className="btn-secondary">
        <HeartIcon filled={saved} className={`size-4 ${saved ? 'text-danger-600' : ''}`} />
        {saved ? 'Saved' : 'Save to wishlist'}
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      aria-pressed={saved}
      aria-label={label}
      title={saved ? 'Remove from wishlist' : 'Save to wishlist'}
      className="grid size-9 place-items-center rounded-full bg-white/95 text-ink-800 shadow-sm ring-1 ring-steel-200 backdrop-blur transition hover:scale-110 hover:text-danger-600 disabled:opacity-60"
    >
      <HeartIcon filled={saved} className={`size-5 ${saved ? 'text-danger-600' : ''}`} />
    </button>
  )
}
