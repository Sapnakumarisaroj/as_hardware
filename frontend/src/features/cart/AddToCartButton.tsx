import { useLocation, useNavigate } from 'react-router'

import { CartIcon } from '@/components/icons'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { savePendingAction } from '@/features/auth/pendingAction'
import { ApiError } from '@/lib/api/errors'

import { useAddToCart } from './api'

interface Props {
  variantId: number
  productName: string
  quantity?: number
  disabled?: boolean
  className?: string
  label?: string
  /** "Buy now": add, then go straight to checkout (Phase 16). */
  buyNow?: boolean
}

/** Adds a specific variant to the server cart; the backend validates stock and price. */
export function AddToCartButton({ variantId, productName, quantity = 1, disabled, className, label, buyNow = false }: Props) {
  const { status } = useAuth()
  const addToCart = useAddToCart()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()

  function handleClick() {
    if (status !== 'authenticated') {
      savePendingAction({ type: 'cart', variantId, quantity, productName })
      toast.show('Sign in to add items to your cart — we’ll add this one for you.', { tone: 'info' })
      const next = buyNow ? '/checkout' : location.pathname + location.search
      navigate(`/login?next=${encodeURIComponent(next)}`)
      return
    }
    addToCart.mutate(
      { variantId, quantity },
      {
        onSuccess: () =>
          buyNow
            ? navigate('/checkout')
            : toast.show(`Added to cart: ${productName}`, { action: { label: 'View cart', to: '/cart' } }),
        onError: (error) =>
          toast.show(error instanceof ApiError ? error.message : 'Could not add to cart.', { tone: 'error' }),
      },
    )
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || addToCart.isPending || status === 'loading'}
      className={className ?? 'btn-primary w-full'}
    >
      {!buyNow && <CartIcon className="size-4" />}
      {addToCart.isPending ? (buyNow ? 'One moment…' : 'Adding…') : (label ?? (buyNow ? 'Buy now' : 'Add to cart'))}
    </button>
  )
}
