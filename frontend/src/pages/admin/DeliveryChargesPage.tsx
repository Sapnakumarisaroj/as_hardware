import { useState } from 'react'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import { useDeliveryCharges, useSaveDeliveryCharges } from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { DistanceBand } from '@/features/admin/types'
import { dateTime, errorMessage, PageHeader, Panel } from '@/features/admin/ui'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const isAmount = (v: string) => v.trim() !== '' && Number(v) >= 0 && Number.isFinite(Number(v))

/** Distance bands (fee by road distance from the store), free delivery on first orders and the unloading fee. */
export function AdminDeliveryChargesPage() {
  usePageMeta('Delivery charges')
  const session = useSession()
  const charges = useDeliveryCharges()
  const save = useSaveDeliveryCharges()
  const toast = useToast()
  const [bands, setBands] = useState<DistanceBand[] | null>(null)
  const [perKm, setPerKm] = useState<string | null>(null)
  const [freeOrders, setFreeOrders] = useState<string | null>(null)
  const [unloading, setUnloading] = useState<string | null>(null)
  const canEdit = session.is_admin

  if (charges.isPending) return <PageSpinner label="Loading delivery charges…" />
  if (charges.isError) return <ErrorState error={charges.error} onRetry={() => void charges.refetch()} />
  const data = charges.data
  const rows = bands ?? data.distance_bands
  const extra = perKm ?? data.extra_per_km ?? ''
  const free = freeOrders ?? String(data.free_first_orders)
  const unloadingFee = unloading ?? data.unloading_fee
  const kms = rows.map((r) => Number(r.up_to_km))
  const bandsInvalid =
    rows.some((r) => !(Number(r.up_to_km) > 0) || !isAmount(r.fee)) || kms.some((km, i) => i > 0 && km <= (kms[i - 1] ?? 0))
  const invalid =
    bandsInvalid || (extra !== '' && !isAmount(extra)) || !/^\d+$/.test(free) || !isAmount(unloadingFee)
  const setRow = (index: number, patch: Partial<DistanceBand>) =>
    setBands(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  const lastKm = rows.at(-1)?.up_to_km

  return (
    <>
      <PageHeader
        title="Delivery charges"
        description="The delivery fee by distance from the store, free delivery on a customer’s first orders and the unloading service. Checkout calculates every charge on the server."
      />
      <Panel title="Fee by distance">
        <form
          noValidate
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (invalid) return
            save.mutate(
              {
                distance_bands: rows,
                extra_per_km: extra === '' ? null : extra,
                free_first_orders: Number(free),
                unloading_fee: unloadingFee,
              },
              {
                onSuccess: () => {
                  toast.show('Delivery charges saved.')
                  setBands(null)
                  setPerKm(null)
                  setFreeOrders(null)
                  setUnloading(null)
                },
                onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
              },
            )
          }}
        >
          <p className="text-sm text-ink-600">
            Distances: <span className="font-semibold">{data.routing}</span>. Estimated distances are labelled as such
            to customers. A zone’s own fee (Django admin › Delivery zones) overrides these bands.
          </p>
          <table className="w-full max-w-md text-left text-sm">
            <caption className="sr-only">Distance bands</caption>
            <thead className="text-xs uppercase text-ink-600">
              <tr>
                <th scope="col" className="py-1">
                  Up to (km)
                </th>
                <th scope="col" className="py-1">
                  Fee (₹)
                </th>
                <th scope="col" className="py-1">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  <td className="py-1 pr-2">
                    <input
                      aria-label={`Band ${index + 1}: up to km`}
                      inputMode="decimal"
                      className="input"
                      value={row.up_to_km}
                      disabled={!canEdit}
                      onChange={(e) => setRow(index, { up_to_km: e.target.value })}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      aria-label={`Band ${index + 1}: fee`}
                      inputMode="decimal"
                      className="input"
                      value={row.fee}
                      disabled={!canEdit}
                      onChange={(e) => setRow(index, { fee: e.target.value })}
                    />
                  </td>
                  <td className="py-1">
                    {canEdit && (
                      <button
                        type="button"
                        className="text-sm font-semibold text-danger-600 hover:underline"
                        onClick={() => setBands(rows.filter((_, i) => i !== index))}
                      >
                        Remove <span className="sr-only">band {index + 1}</span>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {bandsInvalid && (
            <p role="alert" className="text-sm text-danger-600">
              Each band needs a distance above 0 (increasing from row to row) and a fee of ₹0 or more.
            </p>
          )}
          {canEdit && (
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setBands([...rows, { up_to_km: '', fee: '' }])}
            >
              Add band
            </button>
          )}
          <div className="max-w-md space-y-3">
            <FormField
              id="extra-per-km"
              label={`Beyond ${lastKm ?? 'the last band'} km: extra per km (₹)`}
              inputMode="decimal"
              value={extra}
              disabled={!canEdit}
              onChange={(e) => setPerKm(e.target.value)}
              hint={
                extra === ''
                  ? 'Blank: longer distances pay the last band’s fee. Set a rate to charge more for each extra km.'
                  : `Added for every started km above ${lastKm ?? 'the last band'} km.`
              }
            />
            <FormField
              id="free-first-orders"
              label="Free delivery on each customer’s first … orders"
              inputMode="numeric"
              value={free}
              disabled={!canEdit}
              onChange={(e) => setFreeOrders(e.target.value)}
              hint="Counts orders that would otherwise pay a delivery charge; cancelled orders give it back. 0 = off."
            />
            <FormField
              id="unloading-fee"
              label="Unloading service fee (₹)"
              inputMode="decimal"
              value={unloadingFee}
              disabled={!canEdit}
              onChange={(e) => setUnloading(e.target.value)}
              hint="Ground-level unloading only. Offered in zones where it is switched on (Django admin › Delivery zones › Services)."
            />
          </div>
          {canEdit ? (
            <button type="submit" className="btn-primary" disabled={save.isPending || invalid}>
              Save
            </button>
          ) : (
            <p className="text-sm text-ink-600">Only administrators can change delivery charges.</p>
          )}
          <p className="text-xs text-ink-600">
            Last changed {dateTime(data.updated_at)}
            {data.updated_by_name ? ` by ${data.updated_by_name}` : ''}.
          </p>
        </form>
      </Panel>
      <Panel title="Stores and delivery areas" className="mt-4">
        {data.open_coverage_reviews > 0 && (
          <p className="mb-3 rounded-md bg-amber-100 px-3 py-2 text-sm">
            {data.open_coverage_reviews} customer address{data.open_coverage_reviews === 1 ? ' is' : 'es are'} outside the
            delivery area and waiting for review (Django admin › Coverage reviews).
          </p>
        )}
        {data.stores.length === 0 ? (
          <p className="text-sm text-ink-600">No delivering store yet.</p>
        ) : (
          <ul className="space-y-3 text-sm">
            {data.stores.map((store) => (
              <li key={store.id}>
                <p className="font-semibold">{store.name}</p>
                {!store.has_coordinates && (
                  <p className="text-danger-600">
                    Map location missing: distances (and fees) are estimates until the store’s verified latitude and
                    longitude are entered.
                  </p>
                )}
                {store.zones.length === 0 ? (
                  <p className="text-danger-600">No delivery zone: this store can’t deliver anywhere yet.</p>
                ) : (
                  <ul className="list-disc pl-5 text-ink-800">
                    {store.zones.map((zone) => (
                      <li key={zone.id}>
                        {zone.name}
                        {zone.city_wide ? ' · whole city' : ''}
                        {zone.fee_override ? ` · fixed fee ${formatPrice(zone.fee_override)}` : ''}
                        {zone.unloading_available ? ' · unloading offered' : ' · no unloading'}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  )
}
