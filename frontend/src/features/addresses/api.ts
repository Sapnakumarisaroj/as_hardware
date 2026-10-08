import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import { api } from '@/lib/api/client'

export type AddressType = 'home' | 'work' | 'site' | 'other'

export interface Address {
  id: number
  name: string
  phone: string
  address_line1: string
  address_line2: string
  area: string
  landmark: string
  city: string
  state: string
  postal_code: string
  country: string
  latitude: string | null
  longitude: string | null
  address_type: AddressType
  is_default: boolean
  created_at: string
  updated_at: string
}

export type AddressInput = Pick<
  Address,
  'name' | 'phone' | 'address_line1' | 'address_line2' | 'area' | 'landmark' | 'city' | 'state' | 'postal_code' | 'address_type'
> & {
  is_default?: boolean
  /** Map pin (both or neither); null removes it. */
  latitude?: string | null
  longitude?: string | null
}

export const ADDRESS_TYPE_LABELS: Record<AddressType, string> = {
  home: 'Home',
  work: 'Work',
  site: 'Site / project',
  other: 'Other',
}

export const addressKeys = { list: ['addresses'] as const }

export function useAddresses() {
  const { status } = useAuth()
  return useQuery({
    queryKey: addressKeys.list,
    queryFn: async () => (await api.get<Address[]>('/addresses/')).data,
    enabled: status === 'authenticated',
  })
}

function useAddressMutation<TVars, TResult>(request: (vars: TVars) => Promise<TResult>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: () => {
      // Delivery estimates depend on the address (PIN code, map pin).
      void queryClient.invalidateQueries({ queryKey: ['checkout'] })
      void queryClient.invalidateQueries({ queryKey: ['delivery'] })
      return queryClient.invalidateQueries({ queryKey: addressKeys.list })
    },
  })
}

export function useCreateAddress() {
  return useAddressMutation(async (input: AddressInput) => (await api.post<Address>('/addresses/', input)).data)
}

export function useUpdateAddress() {
  return useAddressMutation(
    async ({ id, input }: { id: number; input: AddressInput }) => (await api.patch<Address>(`/addresses/${id}/`, input)).data,
  )
}

export function useDeleteAddress() {
  return useAddressMutation(async (id: number) => {
    await api.delete(`/addresses/${id}/`)
  })
}

export function useSetDefaultAddress() {
  return useAddressMutation(async (id: number) => (await api.post<Address>(`/addresses/${id}/set-default/`)).data)
}

/** "12 MG Road, Ashok Nagar, Bengaluru 560001" */
export function formatAddressLine(address: Pick<Address, 'address_line1' | 'address_line2' | 'area' | 'city' | 'postal_code'>) {
  return [address.address_line1, address.address_line2, address.area, `${address.city} ${address.postal_code}`]
    .filter(Boolean)
    .join(', ')
}
