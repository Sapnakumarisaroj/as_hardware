import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'

import { useAuth } from '@/features/auth/context'
import type { ProductSummary } from '@/features/catalog/types'
import { api } from '@/lib/api/client'

export interface WishlistItem {
  product: ProductSummary
  added_at: string
}

export const wishlistKeys = { list: ['wishlist'] as const }

export function useWishlist() {
  const { status } = useAuth()
  return useQuery({
    queryKey: wishlistKeys.list,
    queryFn: async () => (await api.get<WishlistItem[]>('/wishlist/')).data,
    enabled: status === 'authenticated',
  })
}

/** Product ids on the wishlist, for heart buttons. */
export function useWishlistIds(): Set<number> {
  const { data } = useWishlist()
  return useMemo(() => new Set(data?.map((item) => item.product.id) ?? []), [data])
}

export function useAddToWishlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (productId: number) => {
      await api.post('/wishlist/', { product_id: productId })
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: wishlistKeys.list }),
  })
}

export function useRemoveFromWishlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (productId: number) => {
      await api.delete(`/wishlist/${productId}/`)
    },
    // Removing is safe to show immediately; the list is re-fetched either way.
    onMutate: async (productId) => {
      await queryClient.cancelQueries({ queryKey: wishlistKeys.list })
      const previous = queryClient.getQueryData<WishlistItem[]>(wishlistKeys.list)
      queryClient.setQueryData<WishlistItem[]>(wishlistKeys.list, (items) =>
        items?.filter((item) => item.product.id !== productId),
      )
      return { previous }
    },
    onError: (_error, _productId, context) => {
      if (context?.previous) queryClient.setQueryData(wishlistKeys.list, context.previous)
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: wishlistKeys.list }),
  })
}
