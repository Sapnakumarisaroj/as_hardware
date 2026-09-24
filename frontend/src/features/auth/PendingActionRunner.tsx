import { useEffect, useRef } from 'react'

import { useToast } from '@/components/toast'
import { useAddToCart } from '@/features/cart/api'
import { useAddToWishlist } from '@/features/wishlist/api'
import { ApiError } from '@/lib/api/errors'

import { useAuth } from './context'
import { takePendingAction } from './pendingAction'

/** Completes the wishlist/cart action a shopper attempted before signing in. */
export function PendingActionRunner() {
  const { status } = useAuth()
  const addToCart = useAddToCart()
  const addToWishlist = useAddToWishlist()
  const toast = useToast()
  const ran = useRef(false)

  useEffect(() => {
    if (status !== 'authenticated' || ran.current) return
    ran.current = true
    const action = takePendingAction()
    if (!action) return
    const onError = (error: unknown) =>
      toast.show(error instanceof ApiError ? error.message : 'Could not complete your last action.', { tone: 'error' })
    if (action.type === 'wishlist') {
      addToWishlist.mutate(action.productId, {
        onSuccess: () => toast.show(`Saved to wishlist: ${action.productName}`),
        onError,
      })
    } else {
      addToCart.mutate(
        { variantId: action.variantId, quantity: action.quantity },
        {
          onSuccess: () =>
            toast.show(`Added to cart: ${action.productName}`, { action: { label: 'View cart', to: '/cart' } }),
          onError,
        },
      )
    }
  }, [status, addToCart, addToWishlist, toast])

  useEffect(() => {
    if (status === 'anonymous') ran.current = false
  }, [status])

  return null
}
