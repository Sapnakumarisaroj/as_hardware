import { useState } from 'react'

import { Spinner } from '@/components/feedback'
import { FormField } from '@/components/FormField'
import { Modal } from '@/components/Modal'
import { Pagination } from '@/components/Pagination'
import { useToast } from '@/components/toast'
import {
  useAdjustStock,
  useCreateInventory,
  useInventory,
  useMovements,
  useUpdateInventory,
  useVariantSearch,
} from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { InventoryRow, ManualMovement, VariantHit } from '@/features/admin/types'
import {
  Badge,
  dateTime,
  FilterBar,
  FilterSelect,
  FormDialog,
  label,
  ListView,
  PageHeader,
  SearchBox,
  SelectField,
  TextAreaField,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import { usePageMeta } from '@/lib/usePageMeta'

type Kind = 'received' | 'add' | 'remove' | 'returned'

const KINDS: Record<Kind, { label: string; type: ManualMovement; sign: 1 | -1; hint: string }> = {
  received: { label: 'Stock received', type: 'purchase', sign: 1, hint: 'Goods arrived from a supplier or another store.' },
  add: { label: 'Correction: add', type: 'adjustment', sign: 1, hint: 'More on the shelf than the system shows.' },
  remove: { label: 'Correction: remove', type: 'adjustment', sign: -1, hint: 'Damaged, lost, or fewer on the shelf than shown.' },
  returned: { label: 'Returned to the shelf', type: 'return', sign: 1, hint: 'Sellable goods that came back outside a return request.' },
}

export function StockBadge({ row }: { row: InventoryRow }) {
  if (!row.is_active) return <Badge>Not used</Badge>
  if (row.available_quantity === 0) return <Badge tone="bad">Out of stock</Badge>
  if (row.is_low_stock) return <Badge tone="warn">Low stock</Badge>
  return <Badge tone="good">In stock</Badge>
}

export function AdjustDialog({ row, onClose }: { row: InventoryRow | null; onClose: () => void }) {
  const adjust = useAdjustStock()
  const toast = useToast()
  const [kind, setKind] = useState<Kind>('received')
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState('')
  const [seen, setSeen] = useState<number | null>(null)
  if ((row?.id ?? null) !== seen) {
    setSeen(row?.id ?? null)
    setKind('received')
    setQuantity('')
    setReason('')
    setProblem('')
    adjust.reset()
  }
  if (!row) return null
  const units = Number(quantity)
  const after = row.available_quantity + KINDS[kind].sign * (Number.isInteger(units) && units > 0 ? units : 0)

  function submit() {
    if (!row) return
    if (!Number.isInteger(units) || units <= 0) return setProblem('Enter a whole number of units, 1 or more.')
    if (after < 0) return setProblem(`Only ${row.available_quantity} units are available; stock can’t go below zero.`)
    if (!reason.trim()) return setProblem('Say why the stock changes, so the ledger can be understood later.')
    setProblem('')
    adjust.mutate(
      { id: row.id, movement_type: KINDS[kind].type, quantity: KINDS[kind].sign * units, reason: reason.trim() },
      {
        onSuccess: (movement) => {
          toast.show(`${row.sku}: ${movement.available_after} units available now.`)
          onClose()
        },
      },
    )
  }

  return (
    <FormDialog
      open
      title={`Adjust stock: ${row.product_name}`}
      submitLabel="Record movement"
      busy={adjust.isPending}
      error={adjust.error}
      problem={problem}
      onClose={onClose}
      onSubmit={submit}
    >
      <p className="text-sm text-ink-600">
        {row.store_name} · SKU {row.sku} · {row.available_quantity} available, {row.reserved_quantity} reserved for orders
      </p>
      <SelectField id="movement-kind" label="What happened" value={kind} onChange={(e) => setKind(e.target.value as Kind)} hint={KINDS[kind].hint}>
        {(Object.keys(KINDS) as Kind[]).map((key) => (
          <option key={key} value={key}>
            {KINDS[key].label}
          </option>
        ))}
      </SelectField>
      <FormField
        id="movement-quantity"
        label="Units"
        type="number"
        min={1}
        step={1}
        required
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        hint={units > 0 && after >= 0 ? `Available afterwards: ${after}` : undefined}
      />
      <TextAreaField id="movement-reason" label="Reason" rows={2} required maxLength={255} value={reason} onChange={setReason} />
    </FormDialog>
  )
}

function MovementsDialog({ row, onClose }: { row: InventoryRow | null; onClose: () => void }) {
  const [page, setPage] = useState(1)
  const [seen, setSeen] = useState<number | null>(null)
  if ((row?.id ?? null) !== seen) {
    setSeen(row?.id ?? null)
    setPage(1)
  }
  const movements = useMovements(row?.id ?? null, page)
  if (!row) return null
  return (
    <Modal open onClose={onClose} title={`Stock movements: ${row.sku}`}>
      <p className="mb-3 text-sm text-ink-600">
        {row.product_name} at {row.store_name}. Every change of stock is recorded here and can’t be edited.
      </p>
      {movements.isPending ? (
        <Spinner label="Loading movements…" />
      ) : movements.isError ? (
        <p role="alert" className="text-sm text-danger-600">
          Couldn’t load the movements.
        </p>
      ) : movements.data.results.length === 0 ? (
        <p className="text-sm text-ink-600">No movements yet.</p>
      ) : (
        <>
          <ol className="divide-y divide-steel-100 text-sm">
            {movements.data.results.map((movement) => (
              <li key={movement.id} className="flex items-start justify-between gap-3 py-2">
                <span>
                  <span className="font-semibold">{label(movement.movement_type)}</span>
                  <span className="block text-xs text-ink-600">
                    {dateTime(movement.created_at)}
                    {movement.reason && ` · ${movement.reason}`}
                    {movement.reference_id && ` · ${movement.reference_id}`}
                  </span>
                </span>
                <span className="text-right tabular-nums">
                  <span className={`font-bold ${movement.quantity < 0 ? 'text-danger-600' : 'text-success-600'}`}>
                    {movement.quantity > 0 ? '+' : ''}
                    {movement.quantity}
                  </span>
                  <span className="block text-xs text-ink-600">
                    {movement.available_after} available · {movement.reserved_after} reserved
                  </span>
                </span>
              </li>
            ))}
          </ol>
          <Pagination page={page} pageSize={10} total={movements.data.count} onChange={setPage} />
        </>
      )}
    </Modal>
  )
}

function AddRecordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const session = useSession()
  const create = useCreateInventory()
  const toast = useToast()
  const [store, setStore] = useState('')
  const [term, setTerm] = useState('')
  const [search, setSearch] = useState('')
  const [variant, setVariant] = useState<VariantHit | null>(null)
  const [opening, setOpening] = useState('0')
  const [threshold, setThreshold] = useState('5')
  const hits = useVariantSearch(search)

  function close() {
    create.reset()
    setVariant(null)
    setTerm('')
    setSearch('')
    setOpening('0')
    onClose()
  }

  return (
    <FormDialog
      open={open}
      title="Add a product to a store"
      submitLabel="Add stock record"
      busy={create.isPending}
      error={create.error}
      onClose={close}
      onSubmit={() => {
        if (!store || !variant) return
        create.mutate(
          {
            store: Number(store),
            variant: variant.id,
            opening_quantity: Math.max(Number(opening) || 0, 0),
            low_stock_threshold: Math.max(Number(threshold) || 0, 0),
          },
          {
            onSuccess: () => {
              toast.show(`${variant.sku} is now stocked at this store.`)
              close()
            },
          },
        )
      }}
    >
      <SelectField id="record-store" label="Store or warehouse" required value={store} onChange={(e) => setStore(e.target.value)}>
        <option value="">Choose…</option>
        {session.stores.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </SelectField>
      {variant ? (
        <p className="flex items-center justify-between gap-3 rounded-md bg-steel-50 px-3 py-2 text-sm">
          <span>
            <span className="font-semibold">{variant.product_name}</span> {variant.variant_name}
            <span className="block text-xs text-ink-600">SKU {variant.sku}</span>
          </span>
          <button type="button" className="font-semibold underline-offset-2 hover:underline" onClick={() => setVariant(null)}>
            Change
          </button>
        </p>
      ) : (
        <div>
          <div className="flex items-end gap-2">
            <FormField id="record-search" label="Product" className="flex-1" placeholder="Name or SKU" value={term} onChange={(e) => setTerm(e.target.value)} />
            <button type="button" className="btn-dark" onClick={() => setSearch(term.trim())} disabled={term.trim().length < 2}>
              Find
            </button>
          </div>
          {hits.isFetching && <Spinner label="Searching…" />}
          {hits.data && hits.data.length === 0 && <p className="mt-2 text-sm text-ink-600">No product matches “{search}”.</p>}
          {hits.data && hits.data.length > 0 && (
            <ul className="mt-2 max-h-48 divide-y divide-steel-100 overflow-y-auto rounded-md ring-1 ring-steel-200">
              {hits.data.map((hit) => (
                <li key={hit.id}>
                  <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-steel-50" onClick={() => setVariant(hit)}>
                    <span className="font-semibold">{hit.product_name}</span> {hit.variant_name}
                    <span className="block text-xs text-ink-600">SKU {hit.sku}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <FormField id="record-opening" label="Opening stock" type="number" min={0} value={opening} onChange={(e) => setOpening(e.target.value)} hint="Booked as stock received." />
        <FormField id="record-threshold" label="Low-stock warning at" type="number" min={0} value={threshold} onChange={(e) => setThreshold(e.target.value)} />
      </div>
    </FormDialog>
  )
}

function ThresholdDialog({ row, onClose }: { row: InventoryRow | null; onClose: () => void }) {
  const update = useUpdateInventory()
  const toast = useToast()
  const [value, setValue] = useState('')
  const [seen, setSeen] = useState<number | null>(null)
  if ((row?.id ?? null) !== seen) {
    setSeen(row?.id ?? null)
    setValue(row ? String(row.low_stock_threshold) : '')
    update.reset()
  }
  if (!row) return null
  return (
    <FormDialog
      open
      title={`Low-stock warning: ${row.sku}`}
      busy={update.isPending}
      error={update.error}
      onClose={onClose}
      onSubmit={() =>
        update.mutate(
          { id: row.id, low_stock_threshold: Math.max(Number(value) || 0, 0) },
          {
            onSuccess: () => {
              toast.show('Warning level saved.')
              onClose()
            },
          },
        )
      }
    >
      <FormField
        id="threshold"
        label="Warn when available stock is at or below"
        type="number"
        min={0}
        required
        value={value}
        onChange={(e) => setValue(e.target.value)}
        hint={`${row.product_name} at ${row.store_name}`}
      />
    </FormDialog>
  )
}

export function AdminInventoryPage() {
  usePageMeta('Inventory')
  const session = useSession()
  const list = useListParams()
  const inventory = useInventory({ page: list.page, q: list.get('q'), stock: list.get('stock'), store: list.get('store') })
  const [adjusting, setAdjusting] = useState<InventoryRow | null>(null)
  const [history, setHistory] = useState<InventoryRow | null>(null)
  const [threshold, setThreshold] = useState<InventoryRow | null>(null)
  const [adding, setAdding] = useState(false)

  const columns: Column<InventoryRow>[] = [
    {
      header: 'Product',
      cell: (row) => (
        <>
          <span className="font-semibold">{row.product_name}</span> {row.variant_name}
          <span className="block text-xs text-ink-600">SKU {row.sku}</span>
        </>
      ),
    },
    { header: 'Store', cell: (row) => row.store_name },
    { header: 'Available', numeric: true, cell: (row) => <span className="font-bold">{row.available_quantity}</span> },
    { header: 'Reserved', numeric: true, cell: (row) => row.reserved_quantity },
    { header: 'Warn at', numeric: true, cell: (row) => row.low_stock_threshold },
    { header: 'Status', cell: (row) => <StockBadge row={row} /> },
    {
      header: 'Actions',
      cell: (row) => (
        <span className="flex flex-wrap justify-end gap-1.5 md:justify-start">
          <button type="button" className="btn-primary px-2.5 py-1.5" onClick={() => setAdjusting(row)}>
            Adjust{' '}
<span className="sr-only">stock of {row.sku}</span>
          </button>
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => setHistory(row)}>
            Movements{' '}
<span className="sr-only">of {row.sku}</span>
          </button>
          <button type="button" className="btn-secondary px-2.5 py-1.5" onClick={() => setThreshold(row)}>
            Warning level{' '}
<span className="sr-only">of {row.sku}</span>
          </button>
        </span>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Inventory"
        description="Stock per store. “Reserved” units belong to orders that are not delivered yet. Stock changes only through recorded movements."
        actions={
          <button type="button" className="btn-primary" onClick={() => setAdding(true)} disabled={session.stores.length === 0}>
            Add product to a store
          </button>
        }
      />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by product, SKU or store" />
        <FilterSelect
          list={list}
          name="stock"
          label="Stock"
          options={[
            ['low', 'Low stock'],
            ['out', 'Out of stock'],
            ['ok', 'Enough stock'],
          ]}
        />
        {session.stores.length > 1 && (
          <FilterSelect list={list} name="store" label="Store" all="All stores" options={session.stores.map((s) => [String(s.id), s.name])} />
        )}
      </FilterBar>
      <ListView
        query={inventory}
        list={list}
        caption="Inventory"
        columns={columns}
        rowKey={(row) => row.id}
        empty="No stock records yet"
        emptyHint="Add a product to a store to start tracking its stock."
      />
      <AdjustDialog row={adjusting} onClose={() => setAdjusting(null)} />
      <MovementsDialog row={history} onClose={() => setHistory(null)} />
      <ThresholdDialog row={threshold} onClose={() => setThreshold(null)} />
      <AddRecordDialog open={adding} onClose={() => setAdding(false)} />
    </>
  )
}
