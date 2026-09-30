import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { useCustomer, useCustomers, useUpdateUser } from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { CustomerDetail, CustomerRow, Role } from '@/features/admin/types'
import {
  Badge,
  ConfirmDialog,
  dateTime,
  Facts,
  FilterBar,
  FilterSelect,
  ListView,
  NotAllowed,
  PageHeader,
  Panel,
  SearchBox,
  SelectField,
  StatusBadge,
  useListParams,
  type Column,
} from '@/features/admin/ui'
import { ORDER_STATUS_LABELS } from '@/features/orders/status'
import { isNotFound } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from '../NotFoundPage'

const ROLES: [Role, string][] = [
  ['customer', 'Customer'],
  ['store_manager', 'Store manager'],
  ['delivery_partner', 'Delivery partner'],
  ['admin', 'Administrator'],
]
const ROLE_TEXT = Object.fromEntries(ROLES) as Record<Role, string>

const COLUMNS: Column<CustomerRow>[] = [
  {
    header: 'Customer',
    cell: (person) => (
      <>
        <Link to={`/admin/customers/${person.id}`} className="font-semibold underline-offset-2 hover:underline">
          {person.full_name || person.email}
        </Link>
        {person.role !== 'customer' && <span className="ml-1.5 text-xs text-ink-600">{ROLE_TEXT[person.role]}</span>}
      </>
    ),
  },
  {
    header: 'Contact',
    cell: (person) => (
      <>
        {person.email}
        <span className="block text-xs text-ink-600">{person.phone ?? 'No phone'}</span>
      </>
    ),
  },
  { header: 'Orders', numeric: true, cell: (person) => person.order_count },
  { header: 'Spent', numeric: true, cell: (person) => formatPrice(person.total_spend) },
  { header: 'Last order', cell: (person) => (person.last_order_at ? formatDate(person.last_order_at) : '—') },
  { header: 'Joined', cell: (person) => formatDate(person.date_joined) },
  { header: 'Account', cell: (person) => (person.is_active ? <Badge tone="good">Active</Badge> : <Badge tone="bad">Deactivated</Badge>) },
]

function Customers() {
  const list = useListParams()
  const people = useCustomers({
    page: list.page,
    q: list.get('q'),
    role: list.get('role'),
    is_active: list.get('is_active'),
    has_orders: list.get('has_orders'),
    ordering: list.get('ordering'),
  })
  return (
    <>
      <PageHeader title="Customers" description="Contact details are for serving customers; passwords are never shown anywhere." />
      <FilterBar list={list}>
        <SearchBox list={list} placeholder="Search by name, email or phone" />
        <FilterSelect list={list} name="role" label="Role" all="Customers" options={[...ROLES.slice(1), ['all', 'Everyone']]} />
        <FilterSelect list={list} name="is_active" label="Account" options={[['true', 'Active'], ['false', 'Deactivated']]} />
        <FilterSelect list={list} name="has_orders" label="Orders" options={[['true', 'Has ordered']]} />
        <FilterSelect
          list={list}
          name="ordering"
          label="Sort"
          all="Newest first"
          options={[
            ['-total_spend', 'Highest spend'],
            ['-order_count', 'Most orders'],
            ['-last_order_at', 'Latest order'],
            ['date_joined', 'Oldest first'],
          ]}
        />
      </FilterBar>
      <ListView query={people} list={list} caption="Customers" columns={COLUMNS} rowKey={(person) => person.id} empty="No customers yet" />
    </>
  )
}

export function AdminCustomersPage() {
  usePageMeta('Customers')
  const session = useSession()
  return session.can.manage_customers ? <Customers /> : <NotAllowed what="Customer accounts" />
}

function Account({ person }: { person: CustomerDetail }) {
  const session = useSession()
  const update = useUpdateUser()
  const toast = useToast()
  const [role, setRole] = useState<Role>(person.role)
  const [asking, setAsking] = useState<'status' | 'role' | null>(null)
  const self = person.id === session.user.id
  const close = () => {
    update.reset()
    setAsking(null)
  }

  return (
    <Panel title="Account">
      <Facts
        items={[
          ['Status', person.is_active ? 'Active' : `Deactivated ${person.deactivated_at ? dateTime(person.deactivated_at) : ''}`],
          ['Role', ROLE_TEXT[person.role]],
          ['Email verified', person.email_verified ? 'Yes' : 'No'],
          ['Joined', dateTime(person.date_joined)],
          ['Last sign-in', dateTime(person.last_login)],
          ...(person.managed_stores.length
            ? ([['Manages', person.managed_stores.map((store) => store.name).join(', ')]] as [string, string][])
            : []),
        ]}
      />
      {self ? (
        <p className="mt-3 text-xs text-ink-600">This is your own account. Another administrator can change it.</p>
      ) : (
        <div className="mt-4 space-y-3 border-t border-steel-100 pt-3">
          <button
            type="button"
            className={person.is_active ? 'btn-secondary text-danger-600' : 'btn-primary'}
            onClick={() => setAsking('status')}
          >
            {person.is_active ? 'Deactivate account' : 'Activate account'}
          </button>
          <div className="flex items-end gap-2">
            <SelectField id="role" label="Role" className="flex-1" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map(([value, name]) => (
                <option key={value} value={value}>
                  {name}
                </option>
              ))}
            </SelectField>
            <button type="button" className="btn-secondary" disabled={role === person.role} onClick={() => setAsking('role')}>
              Change role
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={asking !== null}
        title={
          asking === 'role'
            ? `Make ${person.full_name || person.email} ${ROLE_TEXT[role].toLowerCase()}?`
            : `${person.is_active ? 'Deactivate' : 'Activate'} ${person.full_name || person.email}?`
        }
        confirmLabel={asking === 'role' ? 'Change role' : person.is_active ? 'Deactivate' : 'Activate'}
        danger={asking === 'status' && person.is_active}
        busy={update.isPending}
        error={update.error}
        onClose={close}
        onConfirm={() =>
          update.mutate(
            { id: person.id, changes: asking === 'role' ? { role } : { is_active: !person.is_active } },
            {
              onSuccess: () => {
                toast.show('Account updated.')
                close()
              },
            },
          )
        }
      >
        {asking === 'role' ? (
          <p>
            {role === 'admin'
              ? 'Administrators can see and change everything, including other accounts.'
              : role === 'store_manager'
                ? 'Store managers work with the stores assigned to them. Assign a store on the store’s page.'
                : role === 'delivery_partner'
                  ? 'Delivery partners use the rider app. Verify them under Delivery before they get jobs.'
                  : 'The account goes back to an ordinary customer account.'}
          </p>
        ) : person.is_active ? (
          <p>The person is signed out and can’t sign in or order until the account is activated again. Their orders stay as they are.</p>
        ) : (
          <p>The person can sign in and order again.</p>
        )}
      </ConfirmDialog>
    </Panel>
  )
}

function Customer({ id }: { id: string | undefined }) {
  const query = useCustomer(id)
  usePageMeta(query.data?.full_name || 'Customer')
  if (query.isPending) return <PageSpinner label="Loading the customer…" />
  if (isNotFound(query.error)) return <NotFoundPage />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn’t load the customer" />
  const person = query.data

  return (
    <>
      <PageHeader
        title={person.full_name || person.email}
        crumbs={[{ label: 'Customers', to: '/admin/customers' }]}
        actions={person.is_active ? <Badge tone="good">Active</Badge> : <Badge tone="bad">Deactivated</Badge>}
      />
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5">
          <Panel title="Contact">
            <Facts
              items={[
                ['Email', <a href={`mailto:${person.email}`}>{person.email}</a>],
                ['Phone', person.phone ? <a href={`tel:${person.phone}`}>{person.phone}</a> : '—'],
                [
                  'Delivers to',
                  person.addresses.length
                    ? person.addresses.map((a) => [a.area, a.city, a.postal_code].filter(Boolean).join(', ')).join(' · ')
                    : '—',
                ],
              ]}
            />
          </Panel>
          <Account key={`${person.role}-${person.is_active}`} person={person} />
        </div>
        <div className="space-y-5 lg:col-span-2">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                ['Orders', person.order_count],
                ['Spent', formatPrice(person.total_spend)],
                ['Cancelled', person.cancelled_orders],
                ['Returns', person.returns],
              ] as const
            ).map(([name, value]) => (
              <div key={name} className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
                <dt className="text-sm text-ink-600">{name}</dt>
                <dd className="mt-1 text-xl font-extrabold">{value}</dd>
              </div>
            ))}
          </dl>
          <Panel
            title="Recent orders"
            action={
              person.order_count + person.cancelled_orders > 0 && (
                <Link to={`/admin/orders?customer=${person.id}`} className="text-sm font-semibold text-amber-600 hover:underline">
                  All orders
                </Link>
              )
            }
          >
            {person.recent_orders.length === 0 ? (
              <p className="text-sm text-ink-600">No orders yet.</p>
            ) : (
              <ul className="divide-y divide-steel-100 text-sm">
                {person.recent_orders.map((order) => (
                  <li key={order.order_number} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span>
                      <Link to={`/admin/orders/${order.order_number}`} className="font-semibold underline-offset-2 hover:underline">
                        {order.order_number}
                      </Link>
                      <span className="block text-xs text-ink-600">
                        {dateTime(order.created_at)}
                        {order.store_name && ` · ${order.store_name}`}
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      {formatPrice(order.grand_total)}
                      <StatusBadge status={order.status} text={ORDER_STATUS_LABELS[order.status]} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </>
  )
}

export function AdminCustomerPage() {
  const { id } = useParams()
  const session = useSession()
  return session.can.manage_customers ? <Customer id={id} /> : <NotAllowed what="Customer accounts" />
}
