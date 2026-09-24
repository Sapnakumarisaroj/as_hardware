import { Link } from 'react-router'

import { EmptyState, ErrorState, GridSkeleton, PageSpinner, SignInPrompt } from '@/components/feedback'
import { useAuth } from '@/features/auth/context'
import { ProductGrid } from '@/features/catalog/components/ProductCollections'
import { useWishlist } from '@/features/wishlist/api'
import { isUnauthorized } from '@/lib/api/errors'
import { usePageMeta } from '@/lib/usePageMeta'

export function WishlistPage() {
  usePageMeta('Wishlist')
  const { status } = useAuth()
  const wishlist = useWishlist()

  let body
  if (status === 'loading') body = <PageSpinner />
  else if (status === 'anonymous') body = <SignInPrompt message="Login to save items and see them here." next="/wishlist" />
  else if (wishlist.isPending) body = <GridSkeleton count={4} />
  else if (wishlist.isError)
    body = isUnauthorized(wishlist.error) ? (
      <SignInPrompt message="Your session has ended. Please sign in again." next="/wishlist" />
    ) : (
      <ErrorState error={wishlist.error} onRetry={() => wishlist.refetch()} title="Couldn’t load your wishlist" />
    )
  else if (!wishlist.data.length)
    body = (
      <EmptyState
        title="No saved items yet"
        action={
          <Link to="/products" className="btn-primary">
            Browse products
          </Link>
        }
      >
        Tap the heart on any product to save it for later.
      </EmptyState>
    )
  else body = <ProductGrid products={wishlist.data.map((item) => item.product)} />

  return (
    <div className="container-page py-6">
      <h1 className="mb-4 text-2xl font-bold">
        Wishlist{wishlist.data?.length ? ` (${wishlist.data.length})` : ''}
      </h1>
      {body}
    </div>
  )
}
