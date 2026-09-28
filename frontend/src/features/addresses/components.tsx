import { useState, type FormEvent } from 'react'

import { FormField } from '@/components/FormField'
import { Modal } from '@/components/Modal'
import { useToast } from '@/components/toast'
import { ApiError } from '@/lib/api/errors'

import { AddressLocationField } from './AddressLocationField'
import {
  ADDRESS_TYPE_LABELS,
  formatAddressLine,
  useCreateAddress,
  useDeleteAddress,
  useSetDefaultAddress,
  useUpdateAddress,
  type Address,
  type AddressInput,
  type AddressType,
} from './api'

const EMPTY: AddressInput = {
  name: '',
  phone: '',
  address_line1: '',
  address_line2: '',
  area: '',
  landmark: '',
  city: '',
  state: '',
  postal_code: '',
  address_type: 'home',
}

/** Add or edit an address. The backend validates phone and PIN code; its messages show under each field. */
export function AddressFormModal({
  open,
  onClose,
  address,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  address?: Address | null
  onSaved?: (address: Address) => void
}) {
  const create = useCreateAddress()
  const update = useUpdateAddress()
  const [error, setError] = useState<ApiError | null>(null)
  const busy = create.isPending || update.isPending
  const initial: AddressInput = address ? { ...EMPTY, ...address } : EMPTY
  const fieldError = (name: string) => error?.fieldErrors()[name]?.[0]

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const input = Object.fromEntries(
      Object.keys(EMPTY).map((key) => [key, String(form.get(key) ?? '').trim()]),
    ) as unknown as AddressInput
    input.address_type = (form.get('address_type') as AddressType) || 'home'
    if (form.get('is_default')) input.is_default = true
    const latitude = String(form.get('latitude') ?? '')
    const longitude = String(form.get('longitude') ?? '')
    const pinned = latitude !== '' && longitude !== ''
    // Only send the pin when there is one to save or an existing one to remove.
    if (pinned || address?.latitude) {
      input.latitude = pinned ? latitude : null
      input.longitude = pinned ? longitude : null
    }
    setError(null)
    try {
      const saved = address ? await update.mutateAsync({ id: address.id, input }) : await create.mutateAsync(input)
      onSaved?.(saved)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError({ message: 'Could not save the address.', code: 'unknown', status: null }))
    }
  }

  const f = (name: keyof AddressInput) => ({ id: name, defaultValue: String(initial[name] ?? ''), error: fieldError(name) })
  return (
    <Modal open={open} onClose={onClose} title={address ? 'Edit address' : 'Add a delivery address'}>
      <form id="address-form" onSubmit={submit} className="grid gap-3 sm:grid-cols-2" noValidate>
        {error && !Object.keys(error.fieldErrors()).length && (
          <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600 sm:col-span-2">
            {error.message}
          </p>
        )}
        <FormField {...f('name')} label="Full name" autoComplete="name" required />
        <FormField
          {...f('phone')}
          label="Mobile number"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          required
          hint="10-digit mobile number for the delivery partner"
        />
        <FormField {...f('address_line1')} label="House / flat, building, street" autoComplete="address-line1" required className="sm:col-span-2" />
        <FormField {...f('address_line2')} label="Address line 2" autoComplete="address-line2" className="sm:col-span-2" />
        <FormField {...f('area')} label="Area / locality" />
        <FormField {...f('landmark')} label="Landmark" />
        <FormField {...f('postal_code')} label="PIN code" inputMode="numeric" autoComplete="postal-code" maxLength={6} required />
        <FormField {...f('city')} label="City" autoComplete="address-level2" required />
        <FormField {...f('state')} label="State" autoComplete="address-level1" required className="sm:col-span-2" />
        <AddressLocationField
          key={address?.id ?? 'new'}
          initial={
            address?.latitude && address.longitude
              ? { latitude: Number(address.latitude), longitude: Number(address.longitude) }
              : null
          }
        />
        <fieldset className="sm:col-span-2">
          <legend className="label">Address type</legend>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(ADDRESS_TYPE_LABELS) as AddressType[]).map((type) => (
              <label key={type} className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm ring-1 ring-steel-200 has-checked:bg-amber-100 has-checked:ring-amber-500">
                <input type="radio" name="address_type" value={type} defaultChecked={initial.address_type === type} className="accent-amber-600" />
                {ADDRESS_TYPE_LABELS[type]}
              </label>
            ))}
          </div>
        </fieldset>
        {!address?.is_default && (
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" name="is_default" className="size-4 accent-amber-600" />
            Make this my default address
          </label>
        )}
        <div className="flex gap-2 pt-2 sm:col-span-2">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="btn-primary flex-1">
            {busy ? 'Saving…' : 'Save address'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export function AddressText({ address }: { address: Pick<Address, 'name' | 'phone' | 'address_line1' | 'address_line2' | 'area' | 'city' | 'postal_code' | 'state' | 'landmark'> }) {
  return (
    <address className="not-italic">
      <span className="block font-semibold text-ink-900">{address.name}</span>
      <span className="block text-sm text-ink-800">{formatAddressLine(address)}</span>
      {address.landmark && <span className="block text-sm text-ink-600">Near {address.landmark}</span>}
      <span className="block text-sm text-ink-600">
        {address.state} · {address.phone}
      </span>
    </address>
  )
}

/**
 * Saved addresses with edit/delete/default actions. With `selectedId`/`onSelect` each card is
 * a radio option (checkout); without, it is a plain management list (account page).
 */
export function AddressList({
  addresses,
  selectedId,
  onSelect,
}: {
  addresses: Address[]
  selectedId?: number | null
  onSelect?: (id: number) => void
}) {
  const [editing, setEditing] = useState<Address | null>(null)
  const remove = useDeleteAddress()
  const setDefault = useSetDefaultAddress()
  const toast = useToast()
  const selectable = Boolean(onSelect)

  function deleteAddress(address: Address) {
    if (!window.confirm(`Delete the address for ${address.name}?`)) return
    remove.mutate(address.id, {
      onSuccess: () => toast.show('Address deleted'),
      onError: () => toast.show('Could not delete the address.', { tone: 'error' }),
    })
  }

  return (
    <>
      <ul className="space-y-3" role={selectable ? 'radiogroup' : undefined} aria-label={selectable ? 'Delivery address' : undefined}>
        {addresses.map((address) => {
          const selected = selectable && address.id === selectedId
          return (
            <li
              key={address.id}
              className={`rounded-lg bg-white p-4 ring-1 ${selected ? 'ring-2 ring-amber-500' : 'ring-steel-200'}`}
            >
              <div className="flex items-start gap-3">
                {selectable && (
                  <input
                    type="radio"
                    name="delivery-address"
                    id={`address-${address.id}`}
                    checked={selected}
                    onChange={() => onSelect?.(address.id)}
                    className="mt-1 size-5 shrink-0 accent-amber-600"
                    aria-label={`Deliver to ${address.name}, ${formatAddressLine(address)}`}
                  />
                )}
                <label htmlFor={selectable ? `address-${address.id}` : undefined} className={`min-w-0 flex-1 ${selectable ? 'cursor-pointer' : ''}`}>
                  <span className="mb-1 flex flex-wrap gap-1.5">
                    <span className="rounded bg-steel-100 px-1.5 py-0.5 text-xs font-semibold text-ink-800">
                      {ADDRESS_TYPE_LABELS[address.address_type]}
                    </span>
                    {address.is_default && (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-ink-900">Default</span>
                    )}
                  </span>
                  <AddressText address={address} />
                </label>
              </div>
              <div className={`mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm ${selectable ? 'pl-8' : ''}`}>
                <button type="button" onClick={() => setEditing(address)} className="font-semibold text-amber-600 hover:underline">
                  Edit<span className="sr-only"> address for {address.name}</span>
                </button>
                {!address.is_default && (
                  <button
                    type="button"
                    onClick={() => setDefault.mutate(address.id)}
                    disabled={setDefault.isPending}
                    className="font-semibold text-ink-800 hover:underline"
                  >
                    Set as default<span className="sr-only"> ({address.name})</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => deleteAddress(address)}
                  disabled={remove.isPending}
                  className="font-semibold text-danger-600 hover:underline"
                >
                  Delete<span className="sr-only"> address for {address.name}</span>
                </button>
              </div>
            </li>
          )
        })}
      </ul>
      <AddressFormModal open={editing !== null} onClose={() => setEditing(null)} address={editing} />
    </>
  )
}
