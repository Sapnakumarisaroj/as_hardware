import { useMutation, useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api/client'

import type { ProductEnquiryResult } from './types'

/** "Ask about this product": opens a support conversation linked to the product. */
export function useProductEnquiry() {
  return useMutation({
    mutationFn: async (input: { productId: number; message: string }) =>
      (
        await api.post<ProductEnquiryResult>('/support/product-enquiries/', {
          product_id: input.productId,
          message: input.message,
        })
      ).data,
  })
}

export const attachmentPath = (messageId: number, index: number) => `/support/messages/${messageId}/attachments/${index}/`

/** Staff only: the attachment's bytes as an object URL (the API needs the bearer token, so an
 * `<img src>` straight to the API can't be used). Fetched only when staff open the file. */
export function useAttachmentUrl(messageId: number, index: number, enabled = true) {
  return useQuery({
    queryKey: ['support', 'attachment', messageId, index],
    enabled,
    staleTime: 5 * 60 * 1000,
    gcTime: 5 * 60 * 1000,
    retry: false,
    queryFn: async () => {
      const res = await api.get<Blob>(attachmentPath(messageId, index), { responseType: 'blob' })
      return URL.createObjectURL(res.data)
    },
  })
}
