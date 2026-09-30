import { useState } from 'react'
import { Link } from 'react-router'

import { FormField } from '@/components/FormField'
import { useToast } from '@/components/toast'
import {
  useCod,
  useCodHandover,
  useJobs,
  useRiders,
  useShipments,
  useUpdateRider,
  type ShipmentScope,
} from '@/features/admin/api'
import { AssignRiderDialog, ShipmentActions, UnassignDialog } from '@/features/admin/delivery'
import { useSession } from '@/features/admin/session'
import type { CodRow, JobRow, Rider, StaffShipment } from '@/features/admin/types'
import {
  Badge,
  ConfirmDialog,
  dateTime,
  errorMessage,
  FilterBar,
  FilterSelect,
  FormDialog,
  ListView,
  PageHeader,
  SearchBox,
  SelectField,
  StatusBadge,
  Tabs,
  useListParams,
  type Column,
  type ListParams,
} from '@/features/admin/ui'
import { formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const TABS: [string, string][] = [
  ['shipments', 'Shipments'],
  ['riders', 'Delivery partners'],
  ['jobs', 'Job history'],
  ['cod', 'Cash on delivery'],
]

const orderLink = (number: string) => (
  <Link to={`/admin/orders/${number}`} className="font-semibold underline-offset-2 hover:underline">
    {number}
  </Link>
)

// --- Shipments -----------------------------------------------------------------------------------

const SCOPES: [ShipmentScope, string, string][] = [
  ['waiting', 'Waiting for a rider', 'No shipment is waiting for a rider'],
  ['active', 'With a rider', 'No rider is on the way right now'],
  ['failed', 'Failed', 'No failed deliveries'],
  ['delivered', 'Delivered', 'Nothing delivered yet'],
]

function ShipmentsTab({ list }: { list: ListParams }) {
  const scope = (SCOPES.find(([value]) => value === list.get('scope'))?.[0] ?? 'waiting') as ShipmentScope
  const shipments = useShipments(scope, list.page)
  const [assigning, setAssigning] = useState<StaffShipment | null>(null)
  const [unassigning, setUnassigning] = useState<StaffShipment | null>(null)

  const columns: Column<StaffShipment>[] = [
    {
      header: 'Order',
      cell: (shipment) => (
        <>
          {orderLink(shipment.order_number)}
          <span className="block text-xs text-ink-600">
            {shipment.payment_method === 'cod' ? 'Cash on delivery' : 'Paid online'} · {shipment.delivery_type}
          </span>
        </>
      ),
    },
    { header: 'Store', cell: (shipment) => shipment.store_name },
    {
      header: 'Status',
      cell: (shipment) => (
        <>
          <StatusBadge status={shipment.status} text={shipment.status_label} />
          {shipment.failed_at && scope !== 'delivered' && (
            <span className="mt-1 block text-xs text-danger-600">{shipment.failure_note || shipment.failure_reason}</span>
          )}
        </>
      ),
    },
    {
      header: 'Rider',
      cell: (shipment) =>
        shipment.rider ? (
          <>
            {shipment.rider.full_name}
            <span className="block text-xs text-ink-600">{shipment.rider.phone}</span>
          </>
        ) : (
          'Not assigned'
        ),
    },
    {
      header: scope === 'delivered' ? 'Delivered' : 'Promised',
      cell: (shipment) => dateTime(scope === 'delivered' ? shipment.delivered_at : shipment.estimated_delivery_at),
    },
    { header: 'Attempts', numeric: true, cell: (shipment) => shipment.delivery_attempts },
    {
      header: 'Actions',
      cell: (shipment) => <ShipmentActions shipment={shipment} onAssign={setAssigning} onUnassign={setUnassigning} />,
    },
  ]

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Which shipments">
        {SCOPES.map(([value, name]) => (
          <button
            key={value}
            type="button"
            aria-pressed={scope === value}
            onClick={() => list.set({ scope: value === 'waiting' ? '' : value })}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold ring-1 ${scope === value ? 'bg-ink-900 text-white ring-ink-900' : 'bg-white ring-steel-200 hover:bg-steel-50'}`}
          >
            {name}
          </button>
        ))}
      </div>
      <ListView
        query={shipments}
        page={list.page}
        onPage={list.setPage}
        caption="Shipments"
        columns={columns}
        rowKey={(shipment) => shipment.id}
        empty={SCOPES.find(([value]) => value === scope)?.[2] ?? 'No shipments'}
      />
      <AssignRiderDialog shipment={assigning} onClose={() => setAssigning(null)} />
      <UnassignDialog shipment={unassigning} onClose={() => setUnassigning(null)} />
    </>
  )
}

// --- Riders --------------------------------------------------------------------------------------

function RiderDialog({ rider, onClose }: { rider: Rider; onClose: () => void }) {
  const session = useSession()
  const update = useUpdateRider()
  const toast = useToast()
  const [capacity, setCapacity] = useState(String(rider.capacity))
  const [store, setStore] = useState(rider.home_store ? String(rider.home_store) : '')
  const [verified, setVerified] = useState(rider.is_verified)
  const [active, setActive] = useState(rider.is_active)

  return (
    <FormDialog
      open
      title={rider.full_name}
      busy={update.isPending}
      error={update.error}
      onClose={onClose}
      onSubmit={() =>
        update.mutate(
          {
            id: rider.partner_id,
            changes: {
              max_active_assignments: Number(capacity) || 1,
              home_store: store ? Number(store) : null,
              is_verified: verified,
              is_active: active,
            },
          },
          {
            onSuccess: () => {
              toast.show(`${rider.full_name} saved.`)
              onClose()
            },
          },
        )
      }
    >
      <p className="text-sm text-ink-600">
        {rider.email} · {rider.phone} · {rider.vehicle_type} {rider.vehicle_number}
      </p>
      <SelectField id="rider-store" label="Home store" value={store} onChange={(e) => setStore(e.target.value)}>
        <option value="">No home store</option>
        {session.stores
          .filter((s) => s.kind !== 'warehouse')
          .map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
      </SelectField>
      <FormField
        id="rider-capacity"
        label="Deliveries at once"
        type="number"
        min={1}
        max={10}
        required
        value={capacity}
        onChange={(e) => setCapacity(e.target.value)}
      />
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-amber-500" checked={verified} onChange={(e) => setVerified(e.target.checked)} />
        <span>
          <span className="font-medium">Verified</span>
          <span className="block text-xs text-ink-600">Documents checked. Only verified riders get jobs.</span>
        </span>
      </label>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-amber-500" checked={active} onChange={(e) => setActive(e.target.checked)} />
        <span>
          <span className="font-medium">Active</span>
          <span className="block text-xs text-ink-600">Turn off when the rider no longer works with you.</span>
        </span>
      </label>
    </FormDialog>
  )
}

function RidersTab({ list }: { list: ListParams }) {
  const session = useSession()
  const riders = useRiders({ page: list.page, q: list.get('q'), status: list.get('status'), is_verified: list.get('is_verified'), store: list.get('store') })
  const [editing, setEditing] = useState<Rider | null>(null)

  const columns: Column<Rider>[] = [
    {
      header: 'Delivery partner',
      cell: (rider) => (
        <>
          <span className="font-semibold">{rider.full_name}</span>
          <span className="block text-xs text-ink-600">
            {rider.phone} · {rider.vehicle_type} {rider.vehicle_number}
          </span>
        </>
      ),
    },
    { header: 'Store', cell: (rider) => rider.home_store_name ?? '—' },
    {
      header: 'Status',
      cell: (rider) => (
        <span className="flex flex-wrap justify-end gap-1 md:justify-start">
          <StatusBadge status={rider.status} text={rider.status === 'available' ? 'Online' : undefined} />
          {!rider.is_verified && <Badge tone="warn">Not verified</Badge>}
          {!rider.is_active && <Badge tone="bad">Deactivated</Badge>}
        </span>
      ),
    },
    { header: 'Active jobs', numeric: true, cell: (rider) => `${rider.active_assignments} of ${rider.capacity}` },
    {
      header: 'Delivered',
      numeric: true,
      cell: (rider) => (
        <>
          {rider.delivered}
          <span className="block text-xs text-ink-600">
            {rider.delivered_today} today · {rider.failed} failed
          </span>
        </>
      ),
    },
    {
      header: 'Cash in hand',
      numeric: true,
      cell: (rider) =>
        Number(rider.cash_in_hand) > 0 ? (
          <Link to={`/admin/delivery?tab=cod&handed_over=false&partner=${rider.partner_id}`} className="font-bold text-danger-600 underline-offset-2 hover:underline">
            {formatPrice(rider.cash_in_hand)}
          </Link>
        ) : (
          formatPrice(rider.cash_in_hand)
        ),
    },
    {
      header: 'Earnings',
      numeric: true,
      cell: (rider) => (
        <>
          {formatPrice(rider.earnings_total)}
          <span className="block text-xs text-ink-600">
            {formatPrice(rider.earnings_today)} today · {formatPrice(rider.earnings_7_days)} in 7 days
          </span>
        </>
      ),
    },
    ...(session.can.manage_riders
      ? [
          {
            header: 'Actions',
            cell: (rider: Rider) => (
              <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => setEditing(rider)}>
                {rider.is_verified ? 'Edit' : 'Verify'}
                {' '}
<span className="sr-only">{rider.full_name}</span>
              </button>
            ),
          } satisfies Column<Rider>,
        ]
      : []),
  ]

  return (
    <>
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by name, phone or vehicle number" />
        <FilterSelect
          list={list}
          name="status"
          label="Status"
          options={[
            ['online', 'Online'],
            ['available', 'Available'],
            ['busy', 'On a delivery'],
            ['offline', 'Offline'],
          ]}
        />
        <FilterSelect list={list} name="is_verified" label="Verified" options={[['true', 'Verified'], ['false', 'Not verified']]} />
      </FilterBar>
      <ListView
        query={riders}
        list={list}
        caption="Delivery partners"
        columns={columns}
        rowKey={(rider) => rider.partner_id}
        empty="No delivery partners yet"
        emptyHint="Give a person the role “delivery partner” under Customers (the account needs a phone number); they appear here at once, unverified."
      />
      {editing && <RiderDialog rider={editing} onClose={() => setEditing(null)} />}
    </>
  )
}

// --- Job history ---------------------------------------------------------------------------------

const JOB_COLUMNS: Column<JobRow>[] = [
  {
    header: 'Order',
    cell: (job) => (
      <>
        {orderLink(job.order_number)}
        <span className="block text-xs text-ink-600">
          {job.kind === 'return_pickup' ? `Return pickup ${job.return_number ?? ''}` : 'Delivery'}
        </span>
      </>
    ),
  },
  { header: 'Rider', cell: (job) => job.partner_name },
  { header: 'Store', cell: (job) => job.store_name ?? '—' },
  {
    header: 'Status',
    cell: (job) => (
      <>
        <StatusBadge status={job.status} text={job.status_label} />
        {(job.failure_reason || job.reject_reason) && (
          <span className="mt-1 block text-xs text-danger-600">{job.failure_reason || job.reject_reason}</span>
        )}
        {job.completed_without_otp && <span className="mt-1 block text-xs text-ink-600">Closed by staff without the code</span>}
      </>
    ),
  },
  { header: 'Assigned', cell: (job) => dateTime(job.assigned_at) },
  { header: 'Finished', cell: (job) => dateTime(job.delivered_at ?? job.failed_at) },
  { header: 'Earning', numeric: true, cell: (job) => formatPrice(job.earning_amount) },
]

function JobsTab({ list }: { list: ListParams }) {
  const jobs = useJobs({ page: list.page, q: list.get('q'), status: list.get('status'), kind: list.get('kind'), store: list.get('store') })
  return (
    <>
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by order number or rider" />
        <FilterSelect
          list={list}
          name="status"
          label="Status"
          options={[
            ['active', 'In progress'],
            ['completed', 'Completed'],
            ['failed', 'Failed'],
            ['rejected', 'Rejected by the rider'],
            ['cancelled', 'Cancelled or reassigned'],
          ]}
        />
        <FilterSelect list={list} name="kind" label="Type" options={[['delivery', 'Deliveries'], ['return_pickup', 'Return pickups']]} />
      </FilterBar>
      <ListView query={jobs} list={list} caption="Rider jobs" columns={JOB_COLUMNS} rowKey={(job) => job.id} empty="No rider jobs yet" />
    </>
  )
}

// --- Cash on delivery ----------------------------------------------------------------------------

function CodTab({ list }: { list: ListParams }) {
  const cod = useCod({ page: list.page, handed_over: list.get('handed_over'), partner: list.get('partner') })
  const handover = useCodHandover()
  const toast = useToast()
  const [receiving, setReceiving] = useState<CodRow | null>(null)

  const columns: Column<CodRow>[] = [
    { header: 'Order', cell: (row) => orderLink(row.order_number) },
    { header: 'Rider', cell: (row) => row.partner_name },
    { header: 'Store', cell: (row) => row.store_name ?? '—' },
    {
      header: 'Collected',
      numeric: true,
      cell: (row) => (
        <>
          <span className="font-bold">{formatPrice(row.cod_collected_amount)}</span>
          <span className="block text-xs text-ink-600">
            {row.cod_method === 'upi' ? `UPI ${row.cod_reference}` : 'Cash'} · {dateTime(row.cod_collected_at)}
          </span>
        </>
      ),
    },
    {
      header: 'Handover',
      cell: (row) =>
        row.cod_method === 'upi' ? (
          <Badge tone="good">Paid to the store by UPI</Badge>
        ) : row.handed_over ? (
          <>
            <Badge tone="good">Received</Badge>
            <span className="mt-1 block text-xs text-ink-600">
              {dateTime(row.cod_handed_over_at)}
              {row.handed_over_to && ` · ${row.handed_over_to}`}
            </span>
          </>
        ) : (
          <Badge tone="warn">With the rider</Badge>
        ),
    },
    {
      header: 'Actions',
      cell: (row) =>
        row.cod_method === 'cash' && !row.handed_over ? (
          <button
            type="button"
            className="btn-primary px-2.5 py-1.5"
            onClick={() => {
              handover.reset()
              setReceiving(row)
            }}
          >
            Cash received{' '}
<span className="sr-only">for order {row.order_number}</span>
          </button>
        ) : (
          <span className="text-ink-600">—</span>
        ),
    },
  ]

  return (
    <>
      <FilterBar list={list}>
        <FilterSelect list={list} name="handed_over" label="Cash" options={[['false', 'Still with riders'], ['true', 'Handed over']]} />
      </FilterBar>
      <ListView query={cod} list={list} caption="Cash-on-delivery collections" columns={columns} rowKey={(row) => row.assignment_id} empty="No cash collected yet" />
      <ConfirmDialog
        open={receiving !== null}
        title="Cash received from the rider?"
        confirmLabel="Yes, cash received"
        busy={handover.isPending}
        error={handover.error}
        note={{ label: 'Note (optional)', placeholder: 'e.g. counted at the till' }}
        onClose={() => setReceiving(null)}
        onConfirm={(note) => {
          if (!receiving) return
          handover.mutate(
            { id: receiving.assignment_id, note },
            {
              onSuccess: () => {
                toast.show(`Cash for order ${receiving.order_number} recorded.`)
                setReceiving(null)
              },
              onError: (error) => toast.show(errorMessage(error), { tone: 'error' }),
            },
          )
        }}
      >
        <p>
          {receiving?.partner_name} hands over <strong>{formatPrice(receiving?.cod_collected_amount)}</strong> for order{' '}
          {receiving?.order_number}. Count the money before you confirm; this can’t be undone.
        </p>
      </ConfirmDialog>
    </>
  )
}

export function AdminDeliveryPage() {
  usePageMeta('Delivery')
  const list = useListParams()
  const tab = TABS.find(([value]) => value === list.get('tab'))?.[0] ?? 'shipments'

  return (
    <>
      <PageHeader title="Delivery" description="Assign riders, follow deliveries and collect cash-on-delivery money." />
      <Tabs
        label="Delivery"
        tabs={TABS}
        current={tab}
        onChange={(next) =>
          list.set({
            tab: next === 'shipments' ? '' : next,
            ...Object.fromEntries(['q', 'status', 'scope', 'kind', 'handed_over', 'partner', 'is_verified', 'store'].map((key) => [key, ''])),
          })
        }
      />
      <div role="tabpanel" aria-label={TABS.find(([value]) => value === tab)?.[1]}>
        {tab === 'shipments' && <ShipmentsTab list={list} />}
        {tab === 'riders' && <RidersTab list={list} />}
        {tab === 'jobs' && <JobsTab list={list} />}
        {tab === 'cod' && <CodTab list={list} />}
      </div>
    </>
  )
}
