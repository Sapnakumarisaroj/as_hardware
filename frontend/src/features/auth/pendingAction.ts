/**
 * An action a logged-out shopper tried (save to wishlist / add to cart). It is remembered
 * for this browser tab and completed right after they sign in, so nothing is silently lost.
 */
const KEY = 'boltrun.pending-action'

export type PendingAction =
  | { type: 'wishlist'; productId: number; productName: string }
  | { type: 'cart'; variantId: number; quantity: number; productName: string }

export function savePendingAction(action: PendingAction) {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(action))
  } catch {
    // Storage unavailable: the shopper will simply repeat the action after login.
  }
}

export function takePendingAction(): PendingAction | null {
  try {
    const raw = window.sessionStorage.getItem(KEY)
    window.sessionStorage.removeItem(KEY)
    return raw ? (JSON.parse(raw) as PendingAction) : null
  } catch {
    return null
  }
}
