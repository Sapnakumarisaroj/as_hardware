import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
  type UseMutationOptions,
} from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context'
import type { Paginated } from '@/features/catalog/types'
import type { ReturnRequest } from '@/features/orders/types'
import { api } from '@/lib/api/client'

import type {
  AdminBrand,
  AdminCategory,
  AdminCreditEntry,
  AdminOrderDetail,
  AdminOrderRow,
  AdminProduct,
  AdminProductRow,
  AdminReferral,
  AdminSession,
  Analytics,
  BundleInput,
  BundleRow,
  CashbackRuleInput,
  CashbackRuleRow,
  CodRow,
  CollectionInput,
  CollectionPreview,
  CollectionRow,
  Coupon,
  CustomerDetail,
  CustomerRow,
  EligiblePartner,
  FreeDeliveryRuleInput,
  FreeDeliveryRuleRow,
  InventoryRow,
  JobRow,
  LoyaltySettings,
  ManualMovement,
  Offer,
  OptionTypeInput,
  OptionTypeRow,
  PaymentSettings,
  ProductInput,
  RecommendationRuleInput,
  RecommendationRuleRow,
  Rider,
  Role,
  RuleInput,
  SearchExplanation,
  SearchIndexStatus,
  SearchRebuildResult,
  StaffRefund,
  StaffShipment,
  StockMovement,
  StoreDetail,
  StoreRow,
  Summary,
  SupportDetail,
  SupportRow,
  SupportStatus,
  VariantHit,
  Zone,
} from './types'

export const PAGE_SIZE = 20
const LIVE_REFRESH_MS = 60_000

/** Filters as they appear in the URL. Empty values are not sent. */
export type Filters = Record<string, string | number | undefined>

function clean(filters: Filters): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') out[key] = String(value)
  }
  return out
}

export function useIsStaff(): boolean {
  const { status, user } = useAuth()
  return status === 'authenticated' && (user?.role === 'admin' || user?.role === 'store_manager')
}

/** A page of a staff list. The server paginates; the browser never holds a whole table. */
function useList<T>(
  name: string,
  url: string,
  filters: Filters,
  options: { refresh?: boolean; enabled?: boolean } = {},
) {
  const staff = useIsStaff()
  const params = clean({ page_size: PAGE_SIZE, ...filters })
  return useQuery({
    queryKey: ['admin', name, 'list', url, params] as QueryKey,
    queryFn: async () => (await api.get<Paginated<T>>(url, { params })).data,
    enabled: staff && options.enabled !== false,
    placeholderData: keepPreviousData,
    refetchInterval: options.refresh ? LIVE_REFRESH_MS : false,
  })
}

function useAll<T>(name: string, url: string, filters: Filters = {}, enabled = true) {
  const staff = useIsStaff()
  const params = clean(filters)
  return useQuery({
    queryKey: ['admin', name, 'all', params] as QueryKey,
    queryFn: async () => (await api.get<T[]>(url, { params })).data,
    enabled: staff && enabled,
  })
}

function useOne<T>(name: string, url: string, id: string | number | undefined, enabled = true) {
  const staff = useIsStaff()
  return useQuery({
    queryKey: ['admin', name, 'one', String(id)] as QueryKey,
    queryFn: async () => (await api.get<T>(url)).data,
    enabled: staff && enabled && id !== undefined && id !== '',
  })
}

/** A change, after which every list and record of the named areas is fetched again. */
function useChange<TInput, TResult = unknown>(
  run: (input: TInput) => Promise<TResult>,
  refresh: string[],
  options: Pick<UseMutationOptions<TResult, Error, TInput>, 'onSuccess'> = {},
) {
  const queryClient = useQueryClient()
  return useMutation<TResult, Error, TInput>({
    mutationFn: run,
    onSuccess: (...args) => {
      for (const name of refresh) void queryClient.invalidateQueries({ queryKey: ['admin', name] })
      return options.onSuccess?.(...args)
    },
  })
}

// --- Session, dashboard, analytics ---------------------------------------------------------------

export function useAdminSession() {
  const enabled = useIsStaff()
  return useQuery({
    queryKey: ['admin', 'session'],
    queryFn: async () => (await api.get<AdminSession>('/admin/session/')).data,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useSummary(store?: string) {
  const enabled = useIsStaff()
  const params = clean({ store })
  return useQuery({
    queryKey: ['admin', 'summary', params],
    queryFn: async () => (await api.get<Summary>('/admin/summary/', { params })).data,
    enabled,
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useAnalytics(filters: Filters) {
  const enabled = useIsStaff()
  const params = clean(filters)
  return useQuery({
    queryKey: ['admin', 'analytics', params],
    queryFn: async () => (await api.get<Analytics>('/admin/analytics/', { params })).data,
    enabled,
    placeholderData: keepPreviousData,
  })
}

// --- Orders --------------------------------------------------------------------------------------

export const useOrders = (filters: Filters) =>
  useList<AdminOrderRow>('orders', '/admin/orders/', filters, { refresh: true })

export const useOrder = (number: string | undefined) =>
  useOne<AdminOrderDetail>('orders', `/admin/orders/${number}/`, number)

const ORDER_AREAS = ['orders', 'summary', 'shipments', 'jobs', 'riders', 'inventory']

export function useTransitionOrder(number: string) {
  return useChange(
    async (input: { status: string; note: string }) => (await api.post(`/orders/${number}/transition/`, input)).data,
    ORDER_AREAS,
  )
}

// --- Shipments and riders (Phase 10 endpoints) ---------------------------------------------------

export type ShipmentScope = 'waiting' | 'active' | 'failed' | 'delivered'

export const useShipments = (scope: ShipmentScope, page: number) =>
  useList<StaffShipment>('shipments', '/delivery/shipments/', { scope, page }, { refresh: scope !== 'delivered' })

export function useEligiblePartners(shipmentId: number | null) {
  return useAll<EligiblePartner>(
    `eligible-${shipmentId}`,
    `/delivery/shipments/${shipmentId}/eligible-partners/`,
    {},
    shipmentId !== null,
  )
}

export function useAssignShipment() {
  return useChange(
    async (input: { shipment: number; partner_id: number; reassign: boolean; reason?: string }) =>
      (
        await api.post(
          `/delivery/shipments/${input.shipment}/${input.reassign ? 'reassign' : 'assign'}/`,
          input.reassign ? { partner_id: input.partner_id, reason: input.reason ?? '' } : { partner_id: input.partner_id },
        )
      ).data,
    ORDER_AREAS,
  )
}

export function useUnassignShipment() {
  return useChange(
    async (input: { shipment: number; reason: string }) =>
      (await api.post(`/delivery/shipments/${input.shipment}/unassign/`, { reason: input.reason })).data,
    ORDER_AREAS,
  )
}

export const useRiders = (filters: Filters) => useList<Rider>('riders', '/admin/riders/', filters, { refresh: true })

export function useUpdateRider() {
  return useChange(
    async (input: { id: number; changes: Partial<Pick<Rider, 'is_verified' | 'is_active' | 'home_store'>> & { max_active_assignments?: number } }) =>
      (await api.patch<Rider>(`/admin/riders/${input.id}/`, input.changes)).data,
    ['riders', 'summary'],
  )
}

export const useJobs = (filters: Filters) => useList<JobRow>('jobs', '/admin/jobs/', filters)

export const useCod = (filters: Filters) => useList<CodRow>('cod', '/delivery/cod/', filters)

export function useCodHandover() {
  return useChange(
    async (input: { id: number; note: string }) =>
      (await api.post<CodRow>(`/delivery/cod/${input.id}/handover/`, { note: input.note })).data,
    ['cod', 'riders', 'summary'],
  )
}

// --- Catalogue -----------------------------------------------------------------------------------

export const useProducts = (filters: Filters, enabled = true) =>
  useList<AdminProductRow>('products', '/admin/products/', filters, { enabled })

export const useProduct = (id: string | undefined) => useOne<AdminProduct>('products', `/admin/products/${id}/`, id)

export function useSaveProduct(id?: number) {
  return useChange(
    async (input: Partial<ProductInput>) =>
      (id ? await api.patch<AdminProduct>(`/admin/products/${id}/`, input) : await api.post<AdminProduct>('/admin/products/', input))
        .data,
    ['products', 'summary'],
  )
}

/** Publish or unpublish from the list, where the product differs per call. */
export function usePublishProduct() {
  return useChange(
    async (input: { id: number; is_published: boolean }) =>
      (await api.patch<AdminProduct>(`/admin/products/${input.id}/`, { is_published: input.is_published })).data,
    ['products', 'summary'],
  )
}

export function useDeleteProduct() {
  return useChange(async (id: number) => (await api.delete(`/admin/products/${id}/`)).data, ['products', 'summary'])
}

export function useRestoreProduct() {
  return useChange(
    async (id: number) => (await api.post<AdminProduct>(`/admin/products/${id}/restore/`, {})).data,
    ['products', 'summary'],
  )
}

export function useAddProductImage(id: number) {
  return useChange(async (input: { file: File; alt_text: string }) => {
    const form = new FormData()
    form.append('image', input.file)
    form.append('alt_text', input.alt_text)
    return (await api.post<AdminProduct>(`/admin/products/${id}/images/`, form)).data
  }, ['products'])
}

export function useChangeProductImage(id: number) {
  return useChange(
    async (input: { image: number; remove?: boolean; is_primary?: boolean }) =>
      input.remove
        ? (await api.delete<AdminProduct>(`/admin/products/${id}/images/${input.image}/`)).data
        : (await api.patch<AdminProduct>(`/admin/products/${id}/images/${input.image}/`, { is_primary: input.is_primary }))
            .data,
    ['products'],
  )
}

export const useCategories = (flat = false) =>
  useAll<AdminCategory>('categories', '/admin/categories/', flat ? { flat: 'true' } : {})

export const useBrands = (filters: Filters) => useList<AdminBrand>('brands', '/admin/brands/', filters)

type CategoryInput = Partial<Pick<AdminCategory, 'name' | 'parent' | 'description' | 'sort_order' | 'is_active'>>

/** Create (no id), change or delete a record of a simple master-data list. */
function useCrud<TInput, TResult>(url: string, refresh: string[]) {
  const save = useChange(
    async (input: { id?: number; data: TInput }) =>
      (input.id ? await api.patch<TResult>(`${url}${input.id}/`, input.data) : await api.post<TResult>(url, input.data)).data,
    refresh,
  )
  const remove = useChange(async (id: number) => (await api.delete(`${url}${id}/`)).data, refresh)
  return { save, remove }
}

export const useCategoryCrud = () => useCrud<CategoryInput, AdminCategory>('/admin/categories/', ['categories'])
export const useBrandCrud = () =>
  useCrud<Partial<Pick<AdminBrand, 'name' | 'is_active'>>, AdminBrand>('/admin/brands/', ['brands'])
export const useOfferCrud = () => useCrud<RuleInput, Offer>('/admin/offers/', ['offers'])
export const useCouponCrud = () => useCrud<RuleInput, Coupon>('/admin/coupons/', ['coupons'])
export const useZoneCrud = () => useCrud<Partial<Zone>, Zone>('/admin/zones/', ['zones', 'stores'])
export const useStoreCrud = () =>
  useCrud<Partial<StoreDetail> & { manager_ids?: number[] }, StoreDetail>('/admin/stores/', ['stores', 'session', 'summary'])

// --- Inventory -----------------------------------------------------------------------------------

export const useInventory = (filters: Filters) => useList<InventoryRow>('inventory', '/inventory/', filters)

export const useMovements = (inventory: number | null, page: number) =>
  useList<StockMovement>(
    'inventory',
    '/inventory/movements/',
    { inventory: inventory ?? undefined, page, page_size: 10 },
    { enabled: inventory !== null },
  )

export function useAdjustStock() {
  return useChange(
    async (input: { id: number; movement_type: ManualMovement; quantity: number; reason: string }) =>
      (
        await api.post<StockMovement>(`/inventory/${input.id}/adjust/`, {
          movement_type: input.movement_type,
          quantity: input.quantity,
          reason: input.reason,
        })
      ).data,
    ['inventory', 'summary', 'products', 'stores'],
  )
}

export function useUpdateInventory() {
  return useChange(
    async (input: { id: number; low_stock_threshold?: number; is_active?: boolean }) => {
      const { id, ...changes } = input
      return (await api.patch<InventoryRow>(`/inventory/${id}/`, changes)).data
    },
    ['inventory', 'summary'],
  )
}

export function useCreateInventory() {
  return useChange(
    async (input: { store: number; variant: number; opening_quantity: number; low_stock_threshold: number }) =>
      (await api.post<InventoryRow>('/inventory/', input)).data,
    ['inventory', 'summary', 'products', 'stores'],
  )
}

export function useVariantSearch(term: string) {
  return useAll<VariantHit>('variants', '/admin/variants/', { q: term }, term.trim().length >= 2)
}

// --- Stores --------------------------------------------------------------------------------------

export const useStores = (filters: Filters) => useList<StoreRow>('stores', '/admin/stores/', filters)
export const useStore = (id: string | undefined) => useOne<StoreDetail>('stores', `/admin/stores/${id}/`, id)

// --- Offers and coupons --------------------------------------------------------------------------

export const useOffers = (filters: Filters) => useList<Offer>('offers', '/admin/offers/', filters)
export const useCoupons = (filters: Filters) => useList<Coupon>('coupons', '/admin/coupons/', filters)

// --- Customers -----------------------------------------------------------------------------------

export const useCustomers = (filters: Filters) => useList<CustomerRow>('customers', '/admin/customers/', filters)
export const useCustomer = (id: string | undefined) =>
  useOne<CustomerDetail>('customers', `/admin/customers/${id}/`, id)

export function useUpdateUser() {
  return useChange(
    async (input: { id: number; changes: { is_active?: boolean; role?: Role } }) =>
      (await api.patch(`/admin/users/${input.id}/`, input.changes)).data,
    ['customers', 'summary'],
  )
}

// --- Returns and refunds (Phase 7 workflows) -----------------------------------------------------

export const useReturns = (filters: Filters) => useList<ReturnRequest>('returns', '/returns/', filters)

export type ReturnAction = 'approve' | 'reject' | 'receive'

export function useReturnAction() {
  return useChange(
    async (input: { number: string; action: ReturnAction; note: string; restock?: boolean }) =>
      (
        await api.post<ReturnRequest>(`/returns/${input.number}/${input.action}/`, {
          note: input.note,
          ...(input.action === 'receive' ? { restock: input.restock ?? true } : {}),
        })
      ).data,
    ['returns', 'refunds', 'orders', 'summary', 'inventory'],
  )
}

export const useRefunds = (filters: Filters) => useList<StaffRefund>('refunds', '/payments/refunds/', filters)

export function useRefundAction() {
  return useChange(
    async (input: { id: string; action: 'retry' } | { id: string; action: 'mark-processed'; reference: string }) =>
      (
        await api.post<StaffRefund>(
          `/payments/refunds/${input.id}/${input.action}/`,
          input.action === 'retry' ? {} : { reference: input.reference },
        )
      ).data,
    ['refunds', 'returns', 'orders', 'summary'],
  )
}

// --- Support -------------------------------------------------------------------------------------

export const useConversations = (filters: Filters) =>
  useList<SupportRow>('support', '/admin/support/', filters, { refresh: true })

export const useConversation = (id: string | undefined) =>
  useOne<SupportDetail>('support', `/admin/support/${id}/`, id)

export function useReply(id: number) {
  return useChange(
    async (body: string) => (await api.post<SupportDetail>(`/admin/support/${id}/reply/`, { body })).data,
    ['support'],
  )
}

export function useUpdateConversation(id: number) {
  return useChange(
    async (changes: { status?: SupportStatus; assign_to_me?: boolean }) =>
      (await api.patch<SupportDetail>(`/admin/support/${id}/`, changes)).data,
    ['support'],
  )
}

// --- Search index (Phase 13, administrators) -----------------------------------------------------

export function useSearchIndex() {
  const enabled = useIsStaff()
  return useQuery({
    queryKey: ['admin', 'search', 'index'],
    queryFn: async () => (await api.get<SearchIndexStatus>('/admin/search/index/')).data,
    enabled,
  })
}

export function useRebuildSearchIndex() {
  return useChange(
    async (force: boolean) => (await api.post<SearchRebuildResult>('/admin/search/index/rebuild/', { force })).data,
    ['search'],
  )
}

export function useRefreshProductEmbedding() {
  return useChange(
    async (productId: number) =>
      (await api.post<{ status: SearchIndexStatus }>(`/admin/search/index/products/${productId}/`)).data,
    ['search'],
  )
}

/** Every score behind the ranking of `q` (keyword, related words, meaning). Only runs for a query. */
export function useSearchExplain(q: string) {
  const enabled = useIsStaff() && q.trim() !== ''
  return useQuery({
    queryKey: ['admin', 'search', 'explain', q],
    queryFn: async () => (await api.get<SearchExplanation>('/admin/search/explain/', { params: { q } })).data,
    enabled,
  })
}

// --- Phase 15: options, curated lists, free-delivery rules, payment settings ---------------------------

export const useOptionTypes = (filters: Filters = {}) => useAll<OptionTypeRow>('option-types', '/admin/option-types/', filters)
export const useOptionTypeCrud = () =>
  useCrud<OptionTypeInput, OptionTypeRow>('/admin/option-types/', ['option-types', 'products'])

export const useCollections = (filters: Filters = {}) => useAll<CollectionRow>('collections', '/admin/collections/', filters)
export const useCollectionCrud = () => useCrud<CollectionInput, CollectionRow>('/admin/collections/', ['collections'])
export const useCollectionPreview = (id: number | null) =>
  useOne<CollectionPreview>('collections', `/admin/collections/${id}/preview/`, id ?? undefined, id !== null)

export const useFreeDeliveryRules = (filters: Filters = {}) =>
  useAll<FreeDeliveryRuleRow>('free-delivery', '/admin/free-delivery-rules/', filters)
export const useFreeDeliveryRuleCrud = () =>
  useCrud<FreeDeliveryRuleInput, FreeDeliveryRuleRow>('/admin/free-delivery-rules/', ['free-delivery'])

/** Zones of every store, for choosing where a free-delivery rule applies. */
export const useAllZones = () => useAll<Zone>('zones', '/admin/zones/')

export function usePaymentSettings() {
  const staff = useIsStaff()
  return useQuery({
    queryKey: ['admin', 'payment-settings'],
    queryFn: async () => (await api.get<PaymentSettings>('/admin/payment-settings/')).data,
    enabled: staff,
  })
}

export function useSavePaymentSettings() {
  return useChange(
    async (data: Partial<Pick<PaymentSettings, 'cod_enabled' | 'cod_max_order_value'>>) =>
      (await api.patch<PaymentSettings>('/admin/payment-settings/', data)).data,
    ['payment-settings'],
  )
}

// --- Loyalty (Phase 17, administrators) ---------------------------------------------------------------

export function useLoyaltySettings() {
  const staff = useIsStaff()
  return useQuery({
    queryKey: ['admin', 'loyalty', 'settings'],
    queryFn: async () => (await api.get<LoyaltySettings>('/admin/loyalty/settings/')).data,
    enabled: staff,
  })
}

export function useSaveLoyaltySettings() {
  return useChange(
    async (data: Partial<Omit<LoyaltySettings, 'updated_at'>>) =>
      (await api.patch<LoyaltySettings>('/admin/loyalty/settings/', data)).data,
    ['loyalty'],
  )
}

export const useCashbackRules = () => useAll<CashbackRuleRow>('loyalty', '/admin/loyalty/cashback-rules/')
export const useCashbackRuleCrud = () =>
  useCrud<CashbackRuleInput, CashbackRuleRow>('/admin/loyalty/cashback-rules/', ['loyalty'])

export const useLoyaltyLedger = (filters: Filters) =>
  useList<AdminCreditEntry>('loyalty', '/admin/loyalty/ledger/', filters)

export const useReferrals = () => useAll<AdminReferral>('loyalty', '/admin/loyalty/referrals/')

export function useGivePromoCredit() {
  return useChange(
    async (input: { user: number; amount: string; reason: string; expiry_days?: number }) =>
      (await api.post<AdminCreditEntry>('/admin/loyalty/promo-credits/', input)).data,
    ['loyalty'],
  )
}

// --- Smart shopping (Phase 22) -----------------------------------------------------------------------

export const useAdminBundles = () => useAll<BundleRow>('bundles', '/admin/bundles/')
export const useBundleCrud = () => useCrud<BundleInput, BundleRow>('/admin/bundles/', ['bundles'])
export const useRecommendationRules = () => useAll<RecommendationRuleRow>('recommendation-rules', '/admin/recommendation-rules/')
export const useRecommendationRuleCrud = () =>
  useCrud<RecommendationRuleInput, RecommendationRuleRow>('/admin/recommendation-rules/', ['recommendation-rules'])
