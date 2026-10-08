import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ErrorState, PageSpinner, Spinner } from '@/components/feedback'
import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import { useCustomers, useServiceAreas, useStore, useStoreCrud, useStores, useZoneCrud } from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { Day, OpeningHours, StoreDetail, StoreKind, StoreRow, Zone } from '@/features/admin/types'
import {
  Badge,
  CheckField,
  ConfirmDialog,
  errorMessage,
  Facts,
  FilterBar,
  FilterSelect,
  FormDialog,
  ListView,
  NotAllowed,
  PageHeader,
  Panel,
  SearchBox,
  SelectField,
  TextAreaField,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import { isNotFound } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from '../NotFoundPage'

type Mode = 'stores' | 'warehouses'

const NAMES: Record<Mode, { title: string; one: string; kind: string; path: string }> = {
  stores: { title: 'Stores', one: 'store', kind: 'fulfilment', path: '/admin/stores' },
  warehouses: { title: 'Warehouses', one: 'warehouse', kind: 'warehouse', path: '/admin/warehouses' },
}

function StoreStatus({ store }: { store: StoreRow }) {
  if (!store.is_active) return <Badge>Inactive</Badge>
  if (store.kind === 'warehouse') return <Badge tone="good">Active</Badge>
  return store.accepts_orders ? <Badge tone="good">Taking orders</Badge> : <Badge tone="warn">Orders paused</Badge>
}

function AdminStoresPage({ mode }: { mode: Mode }) {
  const names = NAMES[mode]
  usePageMeta(names.title)
  const session = useSession()
  const list = useListParams()
  const stores = useStores({ page: list.page, kind: names.kind, q: list.get('q'), is_active: list.get('is_active') })

  const columns: Column<StoreRow>[] = [
    {
      header: mode === 'stores' ? 'Store' : 'Warehouse',
      cell: (store) => (
        <>
          <Link to={`${names.path}/${store.id}`} className="font-semibold underline-offset-2 hover:underline">
            {store.name}
          </Link>
          <span className="block text-xs text-ink-600">
            {store.code} · {store.kind_label}
          </span>
        </>
      ),
    },
    { header: 'Area', cell: (store) => [store.area, store.city, store.postal_code].filter(Boolean).join(', ') },
    { header: 'Status', cell: (store) => <StoreStatus store={store} /> },
    ...(mode === 'stores'
      ? ([
          { header: 'Open orders', numeric: true, cell: (store) => store.open_orders },
          {
            header: 'Delivery zones',
            numeric: true,
            cell: (store) => (store.zone_count > 0 ? store.zone_count : <Badge tone="bad">No zone: can’t deliver</Badge>),
          },
          { header: 'Packing time', numeric: true, cell: (store) => `${store.avg_prep_minutes} min` },
          { header: 'Map location', cell: (store) => (store.has_location ? 'Set' : <Badge tone="warn">Missing</Badge>) },
        ] satisfies Column<StoreRow>[])
      : []),
  ]

  return (
    <>
      <PageHeader
        title={names.title}
        description={
          mode === 'stores'
            ? 'Shops and dark stores that deliver to customers.'
            : 'Warehouses hold stock for the stores; they don’t deliver to customers.'
        }
        actions={
          session.can.manage_stores && (
            <Link to={`${names.path}/new`} className="btn-primary">
              Add {names.one}
            </Link>
          )
        }
      />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by name, code, area or PIN code" />
        <FilterSelect list={list} name="is_active" label="Status" options={[['true', 'Active'], ['false', 'Inactive']]} />
      </FilterBar>
      <ListView
        query={stores}
        list={list}
        caption={names.title}
        columns={columns}
        rowKey={(store) => store.id}
        empty={session.is_admin ? `No ${names.title.toLowerCase()} yet` : `No ${names.one} is assigned to you yet`}
        emptyHint={session.is_admin ? undefined : 'An administrator assigns store managers to their stores.'}
      />
    </>
  )
}

// --- Opening hours -------------------------------------------------------------------------------

const DAYS: [Day, string][] = [
  ['mon', 'Monday'],
  ['tue', 'Tuesday'],
  ['wed', 'Wednesday'],
  ['thu', 'Thursday'],
  ['fri', 'Friday'],
  ['sat', 'Saturday'],
  ['sun', 'Sunday'],
]

function HoursEditor({ value, onChange, disabled }: { value: OpeningHours; onChange: (hours: OpeningHours) => void; disabled?: boolean }) {
  const always = Object.keys(value).length === 0
  return (
    <fieldset disabled={disabled}>
      <legend className="label">Opening hours</legend>
      <CheckField
        id="always-open"
        label="Open all day, every day"
        checked={always}
        onChange={(checked) =>
          onChange(checked ? {} : Object.fromEntries(DAYS.map(([day]) => [day, ['09:00', '21:00']] as [Day, [string, string]])))
        }
      />
      {!always && (
        <ul className="mt-2 space-y-1.5">
          {DAYS.map(([day, name]) => {
            const hours = value[day] ?? null
            return (
              <li key={day} className="grid grid-cols-[6.5rem_auto_1fr] items-center gap-2 text-sm">
                <span className="font-medium">{name}</span>
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    className="size-4 accent-amber-500"
                    checked={hours !== null}
                    onChange={(e) => onChange({ ...value, [day]: e.target.checked ? ['09:00', '21:00'] : null })}
                  />
                  <span className="sr-only">{name}:</span> open
                </label>
                {hours ? (
                  <span className="flex items-center gap-1.5">
                    <input
                      type="time"
                      aria-label={`${name} opens`}
                      className="input w-auto py-1"
                      value={hours[0]}
                      onChange={(e) => onChange({ ...value, [day]: [e.target.value, hours[1]] })}
                    />
                    to
                    <input
                      type="time"
                      aria-label={`${name} closes`}
                      className="input w-auto py-1"
                      value={hours[1]}
                      onChange={(e) => onChange({ ...value, [day]: [hours[0], e.target.value] })}
                    />
                  </span>
                ) : (
                  <span className="text-ink-600">Closed</span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </fieldset>
  )
}

// --- Store form ----------------------------------------------------------------------------------

interface StoreForm {
  name: string
  code: string
  kind: StoreKind
  phone: string
  email: string
  address_line1: string
  address_line2: string
  area: string
  city: string
  state: string
  postal_code: string
  latitude: string
  longitude: string
  opening_hours: OpeningHours
  avg_prep_minutes: string
  prep_minutes_per_item: string
  own_riders: string
  is_active: boolean
  accepts_orders: boolean
  cod_enabled: boolean
}

const OPERATIONS: (keyof StoreForm)[] = ['phone', 'opening_hours', 'avg_prep_minutes', 'prep_minutes_per_item', 'own_riders', 'accepts_orders']

function toForm(store: StoreDetail | null, kind: StoreKind): StoreForm {
  return {
    name: store?.name ?? '',
    code: store?.code ?? '',
    kind: store?.kind ?? kind,
    phone: store?.phone ?? '',
    email: store?.email ?? '',
    address_line1: store?.address_line1 ?? '',
    address_line2: store?.address_line2 ?? '',
    area: store?.area ?? '',
    city: store?.city ?? '',
    state: store?.state ?? '',
    postal_code: store?.postal_code ?? '',
    latitude: store?.latitude ?? '',
    longitude: store?.longitude ?? '',
    opening_hours: store?.opening_hours ?? {},
    avg_prep_minutes: String(store?.avg_prep_minutes ?? 10),
    prep_minutes_per_item: String(store?.prep_minutes_per_item ?? 1),
    own_riders: String(store?.own_riders ?? 0),
    is_active: store?.is_active ?? true,
    accepts_orders: store?.accepts_orders ?? true,
    cod_enabled: store?.cod_enabled ?? true,
  }
}

function toPayload(form: StoreForm, only: (keyof StoreForm)[] | null) {
  const all = {
    ...form,
    name: form.name.trim(),
    code: form.code.trim(),
    latitude: form.latitude.trim() || null,
    longitude: form.longitude.trim() || null,
    avg_prep_minutes: Number(form.avg_prep_minutes) || 0,
    prep_minutes_per_item: Number(form.prep_minutes_per_item) || 0,
    own_riders: Number(form.own_riders) || 0,
  }
  if (!only) return all
  return Object.fromEntries(only.map((key) => [key, all[key]]))
}

function StoreEditor({ store, mode }: { store: StoreDetail | null; mode: Mode }) {
  const names = NAMES[mode]
  const navigate = useNavigate()
  const toast = useToast()
  const { save } = useStoreCrud()
  const [form, setForm] = useState<StoreForm>(() => toForm(store, mode === 'warehouses' ? 'warehouse' : 'store'))
  const set = <K extends keyof StoreForm>(key: K, value: StoreForm[K]) => setForm((current) => ({ ...current, [key]: value }))
  const all = !store || store.can_edit === 'all'
  const text = (key: keyof StoreForm) => ({
    value: form[key] as string,
    disabled: !all && !OPERATIONS.includes(key),
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => set(key, e.target.value as never),
  })
  const delivers = form.kind !== 'warehouse'

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate(
          { id: store?.id, data: toPayload(form, all ? null : OPERATIONS) as Partial<StoreDetail> },
          {
            onSuccess: (saved) => {
              toast.show(`${saved.name} saved.`)
              if (!store) void navigate(`${names.path}/${saved.id}`, { replace: true })
            },
          },
        )
      }}
    >
      {!all && (
        <p className="rounded-md bg-amber-100 px-3 py-2 text-sm">
          You can change how this store runs day to day: opening hours, packing time, riders, phone and pausing orders. Name,
          address and delivery zones are changed by an administrator.
        </p>
      )}
      <Panel title="Details">
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField id="name" label="Name" required maxLength={120} {...text('name')} />
          <FormField id="code" label="Code" required maxLength={20} hint="Short internal code, e.g. PUN-01." {...text('code')} />
          <SelectField id="kind" label="Type" value={form.kind} disabled={!all} onChange={(e) => set('kind', e.target.value as StoreKind)}>
            <option value="store">Retail store</option>
            <option value="dark_store">Dark store (delivery only)</option>
            <option value="warehouse">Warehouse</option>
          </SelectField>
          <FormField id="phone" label="Phone" inputMode="tel" maxLength={15} {...text('phone')} />
          <FormField id="email" label="Email" type="email" {...text('email')} />
          <FormField id="address_line1" label="Address" required className="sm:col-span-2" {...text('address_line1')} />
          <FormField id="address_line2" label="Address line 2" className="sm:col-span-2" {...text('address_line2')} />
          <FormField id="area" label="Area" {...text('area')} />
          <FormField id="city" label="City" required {...text('city')} />
          <FormField id="state" label="State" required {...text('state')} />
          <FormField id="postal_code" label="PIN code" required inputMode="numeric" maxLength={6} {...text('postal_code')} />
          <FormField
            id="latitude"
            label="Latitude"
            inputMode="decimal"
            placeholder="18.507400"
            hint="Needed for distance and delivery time."
            {...text('latitude')}
          />
          <FormField id="longitude" label="Longitude" inputMode="decimal" placeholder="73.807700" {...text('longitude')} />
        </div>
      </Panel>

      <Panel title="Operations">
        <div className="grid gap-4 lg:grid-cols-2">
          <HoursEditor value={form.opening_hours} onChange={(hours) => set('opening_hours', hours)} />
          <div className="space-y-3">
            {delivers && (
              <>
                <FormField
                  id="avg_prep_minutes"
                  label="Packing time (minutes)"
                  type="number"
                  min={0}
                  max={600}
                  hint="Time to pick and pack an order with one line."
                  {...text('avg_prep_minutes')}
                />
                <FormField
                  id="prep_minutes_per_item"
                  label="Extra minutes per additional line"
                  type="number"
                  min={0}
                  max={120}
                  {...text('prep_minutes_per_item')}
                />
                <FormField
                  id="own_riders"
                  label="Own riders on duty"
                  type="number"
                  min={0}
                  max={200}
                  hint="In-house riders who don’t use the rider app. Counted when estimating delivery time."
                  {...text('own_riders')}
                />
                <CheckField
                  id="accepts_orders"
                  label="Taking new orders"
                  hint="Turn off to pause new orders for a while. Orders already placed are not affected."
                  checked={form.accepts_orders}
                  onChange={(checked) => set('accepts_orders', checked)}
                />
              </>
            )}
            <CheckField
              id="is_active"
              label="Active"
              hint="An inactive store is not used for orders or stock checks."
              checked={form.is_active}
              disabled={!all}
              onChange={(checked) => set('is_active', checked)}
            />
            {form.kind !== 'warehouse' && (
              <CheckField
                id="cod_enabled"
                label="Cash on delivery"
                hint="Allow cash on delivery for orders shipped from here. The shop-wide limit still applies."
                checked={form.cod_enabled}
                disabled={!all}
                onChange={(checked) => set('cod_enabled', checked)}
              />
            )}
          </div>
        </div>
      </Panel>

      {save.isError && (
        <p role="alert" className="rounded-md bg-danger-600/10 px-4 py-3 text-sm text-danger-600">
          {errorMessage(save.error)}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Link to={names.path} className="btn-secondary">
          Cancel
        </Link>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : store ? 'Save changes' : `Add ${names.one}`}
        </button>
      </div>
    </form>
  )
}

// --- Delivery zones ------------------------------------------------------------------------------

interface ZoneForm {
  id?: number
  name: string
  service_area: string
  radius_km: string
  postal_codes: string
  fast_delivery_enabled: boolean
  fast_delivery_max_minutes: string
  delivery_fee_override: string
  free_delivery_min_order: string
  cod_enabled: boolean
  is_active: boolean
}

function Zones({ store }: { store: StoreDetail }) {
  const { save, remove } = useZoneCrud()
  const areas = useServiceAreas()
  const toast = useToast()
  const [form, setForm] = useState<ZoneForm | null>(null)
  const [deleting, setDeleting] = useState<Zone | null>(null)
  const canEdit = store.can_edit === 'all'
  const set = <K extends keyof ZoneForm>(key: K, value: ZoneForm[K]) => setForm((current) => (current ? { ...current, [key]: value } : current))

  const open = (zone: Zone | null) => {
    save.reset()
    setForm({
      id: zone?.id,
      name: zone?.name ?? '',
      service_area: zone?.service_area ? String(zone.service_area) : '',
      radius_km: zone?.radius_km ?? '5.00',
      postal_codes: zone?.pin_codes.join(', ') ?? '',
      fast_delivery_enabled: zone?.fast_delivery_enabled ?? true,
      fast_delivery_max_minutes: zone?.fast_delivery_max_minutes ? String(zone.fast_delivery_max_minutes) : '',
      delivery_fee_override: zone?.delivery_fee_override ?? '',
      free_delivery_min_order: zone?.free_delivery_min_order ?? '',
      cod_enabled: zone?.cod_enabled ?? true,
      is_active: zone?.is_active ?? true,
    })
  }

  return (
    <Panel
      title="Delivery zones"
      action={
        canEdit && (
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => open(null)}>
            Add zone
          </button>
        )
      }
    >
      {store.zones.length === 0 ? (
        <p className="text-sm text-ink-600">No delivery zone yet. Without one, this store can’t deliver to any address.</p>
      ) : (
        <ul className="divide-y divide-steel-100">
          {store.zones.map((zone) => (
            <li key={zone.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0 text-sm">
                <p className="font-semibold">
                  {zone.name} {!zone.is_active && <Badge>Inactive</Badge>}
                </p>
                <p className="text-ink-600">
                  {zone.service_area_name ? `All of ${zone.service_area_name} · ` : ''}Within {zone.radius_km} km
                  {zone.pin_codes.length > 0 && ` · PIN codes ${zone.pin_codes.join(', ')}`}
                  {zone.polygon && ' · drawn area'}
                </p>
                <p className="text-ink-600">
                  Delivery {formatPrice(zone.effective_fee)}, free from {formatPrice(zone.effective_free_from)} ·{' '}
                  {zone.fast_delivery_enabled
                    ? `fast delivery${zone.fast_delivery_max_minutes ? ` up to ${zone.fast_delivery_max_minutes} min` : ''}`
                    : 'standard delivery only'}
                </p>
              </div>
              {canEdit && (
                <span className="flex gap-1.5">
                  <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => open(zone)}>
                    Edit{' '}
<span className="sr-only">zone {zone.name}</span>
                  </button>
                  <button type="button" className="btn-secondary px-2.5 py-1.5 text-danger-600" onClick={() => setDeleting(zone)}>
                    Delete{' '}
<span className="sr-only">zone {zone.name}</span>
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <FormDialog
        open={form !== null}
        title={form?.id ? 'Edit delivery zone' : 'Add delivery zone'}
        busy={save.isPending}
        error={save.error}
        onClose={() => setForm(null)}
        onSubmit={() => {
          if (!form) return
          save.mutate(
            {
              id: form.id,
              data: {
                store: store.id,
                name: form.name.trim(),
                service_area: form.service_area ? Number(form.service_area) : null,
                radius_km: form.radius_km,
                postal_codes: form.postal_codes,
                fast_delivery_enabled: form.fast_delivery_enabled,
                fast_delivery_max_minutes: form.fast_delivery_max_minutes ? Number(form.fast_delivery_max_minutes) : null,
                delivery_fee_override: form.delivery_fee_override || null,
                free_delivery_min_order: form.free_delivery_min_order || null,
                cod_enabled: form.cod_enabled,
                is_active: form.is_active,
              },
            },
            {
              onSuccess: () => {
                toast.show('Delivery zone saved.')
                setForm(null)
              },
            },
          )
        }}
      >
        {form && (
          <>
            <FormField id="zone-name" label="Name" required maxLength={120} value={form.name} onChange={(e) => set('name', e.target.value)} />
            <SelectField
              id="zone-area"
              label="City-wide coverage"
              value={form.service_area}
              onChange={(e) => set('service_area', e.target.value)}
              hint="Serve every address in the city. Delivery time is still worked out per address; fast delivery only where the estimate allows."
            >
              <option value="">None (radius and PIN codes only)</option>
              {(areas.data ?? []).map((area) => (
                <option key={area.id} value={area.id} disabled={!area.is_active}>
                  All of {area.name}
                  {area.is_active ? '' : ' (inactive)'}
                </option>
              ))}
            </SelectField>
            <FormField
              id="zone-radius"
              label="Radius (km)"
              required
              inputMode="decimal"
              value={form.radius_km}
              onChange={(e) => set('radius_km', e.target.value)}
              hint="Straight-line distance from the store."
            />
            <TextAreaField
              id="zone-pins"
              label="PIN codes always served"
              rows={2}
              value={form.postal_codes}
              onChange={(value) => set('postal_codes', value)}
              hint="Separated by commas or spaces. Addresses with these PIN codes are served even without a map location."
            />
            <CheckField id="zone-fast" label="Fast delivery in this zone" checked={form.fast_delivery_enabled} onChange={(v) => set('fast_delivery_enabled', v)} />
            <div className="grid grid-cols-2 gap-3">
              <FormField
                id="zone-fast-max"
                label="Fast only up to (min)"
                type="number"
                min={1}
                value={form.fast_delivery_max_minutes}
                onChange={(e) => set('fast_delivery_max_minutes', e.target.value)}
                hint="Empty: shop setting."
              />
              <FormField
                id="zone-fee"
                label="Delivery fee (₹)"
                inputMode="decimal"
                value={form.delivery_fee_override}
                onChange={(e) => set('delivery_fee_override', e.target.value)}
                hint="Empty: shop setting."
              />
              <FormField
                id="zone-free"
                label="Free delivery from (₹)"
                inputMode="decimal"
                value={form.free_delivery_min_order}
                onChange={(e) => set('free_delivery_min_order', e.target.value)}
                hint="Empty: shop setting."
              />
            </div>
            <CheckField
              id="zone-cod"
              label="Cash on delivery in this zone"
              checked={form.cod_enabled}
              onChange={(v) => set('cod_enabled', v)}
            />
            <CheckField id="zone-active" label="Active" checked={form.is_active} onChange={(v) => set('is_active', v)} />
          </>
        )}
      </FormDialog>
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete zone ${deleting?.name ?? ''}?`}
        confirmLabel="Delete zone"
        danger
        busy={remove.isPending}
        error={remove.error}
        onClose={() => {
          remove.reset()
          setDeleting(null)
        }}
        onConfirm={() => {
          if (!deleting) return
          remove.mutate(deleting.id, {
            onSuccess: () => {
              toast.show('Delivery zone deleted.')
              setDeleting(null)
            },
          })
        }}
      >
        <p>Addresses that only this zone covers can no longer order from {store.name}. Orders already placed are delivered as promised.</p>
      </ConfirmDialog>
    </Panel>
  )
}

// --- Managers ------------------------------------------------------------------------------------

function ManagersDialog({ store, onClose }: { store: StoreDetail; onClose: () => void }) {
  const people = useCustomers({ role: 'store_manager', is_active: 'true', page_size: 100 })
  const { save } = useStoreCrud()
  const toast = useToast()
  const [chosen, setChosen] = useState<number[]>(() => store.managers.map((manager) => manager.id))

  return (
    <FormDialog
      open
      title={`Managers of ${store.name}`}
      busy={save.isPending}
      error={save.error}
      onClose={onClose}
      onSubmit={() =>
        save.mutate(
          { id: store.id, data: { manager_ids: chosen } },
          {
            onSuccess: () => {
              toast.show('Managers saved.')
              onClose()
            },
          },
        )
      }
    >
      <p className="text-sm text-ink-600">
        A store manager sees and handles the orders, stock, riders and returns of the stores assigned to them, and nothing else.
      </p>
      {people.isPending ? (
        <Spinner label="Loading store managers…" />
      ) : people.isError ? (
        <p role="alert" className="text-sm text-danger-600">
          Couldn’t load the store managers.
        </p>
      ) : people.data.results.length === 0 ? (
        <p className="rounded-md bg-amber-100 px-3 py-2 text-sm">
          Nobody has the role “store manager” yet. Open a person under Customers and change their role first.
        </p>
      ) : (
        <fieldset>
          <legend className="label">Store managers</legend>
          <ul className="space-y-2">
            {people.data.results.map((person) => (
              <li key={person.id}>
                <CheckField
                  id={`manager-${person.id}`}
                  label={person.full_name || person.email}
                  hint={person.email}
                  checked={chosen.includes(person.id)}
                  onChange={(checked) => setChosen((ids) => (checked ? [...ids, person.id] : ids.filter((id) => id !== person.id)))}
                />
              </li>
            ))}
          </ul>
        </fieldset>
      )}
    </FormDialog>
  )
}

function Managers({ store }: { store: StoreDetail }) {
  const [editing, setEditing] = useState(false)
  return (
    <Panel
      title="Managers"
      action={
        store.can_edit === 'all' && (
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => setEditing(true)}>
            Change{' '}
<span className="sr-only">managers</span>
          </button>
        )
      }
    >
      {store.managers.length === 0 ? (
        <p className="text-sm text-ink-600">No store manager is assigned.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {store.managers.map((manager) => (
            <li key={manager.id}>
              <span className="font-medium">{manager.name || manager.email}</span>
              <span className="block text-xs text-ink-600">{manager.email}</span>
            </li>
          ))}
        </ul>
      )}
      {editing && <ManagersDialog store={store} onClose={() => setEditing(false)} />}
    </Panel>
  )
}

// --- Detail --------------------------------------------------------------------------------------

function AdminStorePage({ mode }: { mode: Mode }) {
  const names = NAMES[mode]
  const { id } = useParams()
  const creating = id === 'new'
  const session = useSession()
  const navigate = useNavigate()
  const toast = useToast()
  const query = useStore(creating ? undefined : id)
  const { remove } = useStoreCrud()
  const [deleting, setDeleting] = useState(false)
  usePageMeta(creating ? `Add ${names.one}` : (query.data?.name ?? names.title))
  const crumbs = [{ label: names.title, to: names.path }]

  if (creating) {
    if (!session.can.manage_stores) return <NotAllowed what="Stores and warehouses" />
    return (
      <>
        <PageHeader title={`Add ${names.one}`} crumbs={crumbs} />
        <StoreEditor store={null} mode={mode} />
      </>
    )
  }
  if (query.isPending) return <PageSpinner label={`Loading the ${names.one}…`} />
  if (isNotFound(query.error)) return <NotFoundPage />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title={`Couldn’t load the ${names.one}`} />
  const store = query.data
  const delivers = store.kind !== 'warehouse'

  return (
    <>
      <PageHeader
        title={store.name}
        crumbs={crumbs}
        description={`${store.code} · ${store.kind_label}`}
        actions={
          <>
            <StoreStatus store={store} />
            {store.can_edit === 'all' && (
              <button type="button" className="btn-secondary text-danger-600" onClick={() => setDeleting(true)}>
                Remove
              </button>
            )}
          </>
        }
      />
      <div className="mb-5 grid gap-5 lg:grid-cols-3">
        <Panel
          title="Stock"
          action={
            <Link to={`/admin/inventory?store=${store.id}`} className="text-sm font-semibold text-amber-700 hover:underline">
              Open inventory
            </Link>
          }
        >
          <Facts
            items={[
              ['Products stocked', store.inventory.stock_records],
              ['Units available', store.inventory.units_available.toLocaleString('en-IN')],
              ['Units reserved', store.inventory.units_reserved.toLocaleString('en-IN')],
              ['Low on stock', store.inventory.low_stock],
              ['Out of stock', store.inventory.out_of_stock],
            ]}
          />
        </Panel>
        {delivers && (
          <Panel
            title="Orders and riders"
            action={
              <Link to={`/admin/orders?store=${store.id}&status=open`} className="text-sm font-semibold text-amber-700 hover:underline">
                Open orders
              </Link>
            }
          >
            <Facts
              items={[
                ['Orders in progress', store.open_orders],
                ['Delivery partners', store.riders.partners],
                ['Online now', store.riders.online],
                ['Own riders on duty', store.riders.own_riders],
              ]}
            />
          </Panel>
        )}
        <Managers store={store} />
      </div>

      {delivers && (
        <div className="mb-5">
          <Zones store={store} />
        </div>
      )}
      {store.can_edit === 'none' ? (
        <NotAllowed what="This store" />
      ) : (
        <StoreEditor key={`${store.id}-${store.zone_count}`} store={store} mode={mode} />
      )}

      <ConfirmDialog
        open={deleting}
        title={`Remove ${store.name}?`}
        confirmLabel={`Remove ${names.one}`}
        danger
        busy={remove.isPending}
        error={remove.error}
        onClose={() => {
          remove.reset()
          setDeleting(false)
        }}
        onConfirm={() =>
          remove.mutate(store.id, {
            onSuccess: () => {
              toast.show(`${store.name} removed.`)
              void navigate(names.path, { replace: true })
            },
          })
        }
      >
        <p>
          A {names.one} can be removed only when it holds no stock and has no orders in progress. Past orders keep pointing to it.
          To stop using it for a while, make it inactive instead.
        </p>
      </ConfirmDialog>
    </>
  )
}

export const AdminStoresListPage = () => <AdminStoresPage mode="stores" />
export const AdminWarehousesListPage = () => <AdminStoresPage mode="warehouses" />
export const AdminStoreDetailPage = () => <AdminStorePage mode="stores" />
export const AdminWarehouseDetailPage = () => <AdminStorePage mode="warehouses" />
