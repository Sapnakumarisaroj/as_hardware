import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { EmptyState, ErrorState, PageSpinner, SignInPrompt } from '@/components/feedback'
import { Pagination } from '@/components/Pagination'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import {
  JOBS_PAGE_SIZE,
  useEarnings,
  useJob,
  useJobs,
  useJobStep,
  useRiderProfile,
  useSaveNotes,
  useSetAvailability,
} from '@/features/rider/api'
import {
  CompleteDeliveryForm,
  FailDialog,
  ItemList,
  JobStatusBadge,
  LocationCard,
  ProofUpload,
  RejectDialog,
} from '@/features/rider/components'
import type { Job } from '@/features/rider/types'
import { ApiError, isNotFound } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

/** The rider area is for delivery partners; everyone else is told so (the API refuses them too). */
function useRider(next: string): ReactNode | null {
  const { status, user } = useAuth()
  if (status === 'loading') return <PageSpinner />
  if (!user) {
    return (
      <div className="container-page py-10">
        <SignInPrompt message="Sign in with your delivery partner account." next={next} />
      </div>
    )
  }
  if (user.role !== 'delivery_partner') {
    return (
      <div className="container-page py-10">
        <EmptyState
          title="For delivery partners only"
          action={
            <Link to="/" className="btn-primary">
              Go to the shop
            </Link>
          }
        >
          This account is not a delivery partner account.
        </EmptyState>
      </div>
    )
  }
  return null
}

function time(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  })
}

function Availability() {
  const profile = useRiderProfile()
  const change = useSetAvailability()
  const toast = useToast()
  if (profile.isPending) return <div className="h-28 animate-pulse rounded-lg bg-white ring-1 ring-steel-200" />
  if (profile.isError) return <ErrorState error={profile.error} onRetry={() => profile.refetch()} title="Couldn’t load your profile" />
  const me = profile.data
  const online = me.status !== 'offline'
  const blocked = !me.is_active ? 'Your account is deactivated. Contact the store.' : !me.is_verified ? 'Your account is waiting for verification by the store.' : ''

  function toggle() {
    change.mutate(online ? 'offline' : 'available', {
      onSuccess: (next) => toast.show(next.status === 'offline' ? 'You are offline. No new jobs will be assigned.' : 'You are online.'),
      onError: (error) => toast.show(error instanceof ApiError ? error.message : 'Could not change your status.', { tone: 'error' }),
    })
  }

  return (
    <section aria-labelledby="availability-heading" className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="availability-heading" className="text-base font-bold">
            {me.full_name}
          </h2>
          <p className="text-sm text-ink-600">
            {me.home_store_name ?? 'No home store'} · {me.vehicle_type}
            {me.vehicle_number && ` ${me.vehicle_number}`} · {me.phone}
          </p>
          <p className="mt-1 text-sm" role="status">
            <span
              aria-hidden
              className={`mr-1.5 inline-block size-2.5 rounded-full ${me.status === 'offline' ? 'bg-steel-200' : me.status === 'busy' ? 'bg-amber-500' : 'bg-success-600'}`}
            />
            <span className="font-semibold">
              {me.status === 'offline' ? 'Offline' : me.status === 'busy' ? 'Online · on a job' : 'Online · available'}
            </span>
            <span className="text-ink-600">
              {' '}
              · {me.active_assignments} of {me.max_active_assignments} active {me.max_active_assignments === 1 ? 'job' : 'jobs'}
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={toggle}
          disabled={change.isPending || Boolean(blocked) || me.active_assignments > 0}
          aria-pressed={online}
          className={online ? 'btn-secondary' : 'btn-primary'}
        >
          {change.isPending ? 'Saving…' : online ? 'Go offline' : 'Go online'}
        </button>
      </div>
      {blocked && (
        <p role="alert" className="mt-2 text-sm text-danger-600">
          {blocked}
        </p>
      )}
      {!blocked && me.active_assignments > 0 && <p className="mt-2 text-xs text-ink-600">Finish your active job before going offline.</p>}
    </section>
  )
}

function Money() {
  const earnings = useEarnings()
  if (!earnings.data) return null
  const e = earnings.data
  const tile = 'rounded-lg bg-white p-4 ring-1 ring-steel-200'
  return (
    <section aria-labelledby="earnings-heading">
      <h2 id="earnings-heading" className="mb-2 text-base font-bold">
        Earnings and cash
      </h2>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className={tile}>
          <dt className="text-xs text-ink-600">Today</dt>
          <dd className="text-lg font-bold">{formatPrice(e.today_earnings)}</dd>
          <dd className="text-xs text-ink-600">
            {e.today_delivered_count} {e.today_delivered_count === 1 ? 'job' : 'jobs'} done
          </dd>
        </div>
        <div className={tile}>
          <dt className="text-xs text-ink-600">Last 7 days</dt>
          <dd className="text-lg font-bold">{formatPrice(e.last_7_days_earnings)}</dd>
        </div>
        <div className={tile}>
          <dt className="text-xs text-ink-600">All time</dt>
          <dd className="text-lg font-bold">{formatPrice(e.total_earnings)}</dd>
          <dd className="text-xs text-ink-600">
            {e.delivered_count} done · {e.failed_count} failed
          </dd>
        </div>
        <div className={`${tile} ${e.cash_in_hand !== '0.00' ? 'ring-2 ring-amber-500' : ''}`}>
          <dt className="text-xs text-ink-600">Cash to hand over</dt>
          <dd className="text-lg font-bold">{formatPrice(e.cash_in_hand)}</dd>
          <dd className="text-xs text-ink-600">
            {e.cash_deliveries_pending_handover
              ? `From ${e.cash_deliveries_pending_handover} ${e.cash_deliveries_pending_handover === 1 ? 'delivery' : 'deliveries'}. Give it to the store.`
              : 'Nothing to hand over'}
          </dd>
        </div>
      </dl>
    </section>
  )
}

function JobRow({ job }: { job: Job }) {
  const place = job.kind === 'return_pickup' ? job.pickup : job.drop
  const where = [place?.area, place?.city].filter(Boolean).join(', ')
  return (
    <li>
      <Link to={`/rider/jobs/${job.id}`} className="block rounded-lg bg-white p-4 ring-1 ring-steel-200 hover:ring-amber-500">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold">
            {job.kind === 'return_pickup' ? 'Return pickup' : 'Delivery'} · <span className="sr-only">order</span>{' '}
            {job.order_number}
          </p>
          <JobStatusBadge job={job} />
        </div>
        <p className="mt-1 text-sm text-ink-800">
          {job.items.reduce((sum, item) => sum + item.quantity, 0)} item(s){where && ` · ${where}`}
          {job.distance_km && ` · ${Number(job.distance_km).toFixed(1)} km`}
        </p>
        <p className="mt-1 text-xs text-ink-600">
          Assigned {time(job.assigned_at)}
          {job.amount_to_collect && (
            <span className="ml-2 font-semibold text-ink-900">Collect {formatPrice(job.amount_to_collect)}</span>
          )}
          {job.status === 'delivered' && <span className="ml-2">Earned {formatPrice(job.earning_amount)}</span>}
        </p>
      </Link>
    </li>
  )
}

export function RiderDashboardPage() {
  usePageMeta('Rider app')
  const gate = useRider('/rider')
  const jobs = useJobs('active')
  if (gate) return gate

  let list
  if (jobs.isPending) list = <PageSpinner label="Loading your jobs…" />
  else if (jobs.isError) list = <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} title="Couldn’t load your jobs" />
  else if (!jobs.data.results.length)
    list = (
      <EmptyState title="No active jobs">Stay online: the store assigns new deliveries to available partners.</EmptyState>
    )
  else
    list = (
      <ul className="space-y-3">
        {jobs.data.results.map((job) => (
          <JobRow key={job.id} job={job} />
        ))}
      </ul>
    )

  return (
    <div className="container-page max-w-3xl space-y-6 py-6">
      <h1 className="text-2xl font-bold">Rider app</h1>
      <Availability />
      <section aria-labelledby="active-heading">
        <div className="mb-2 flex items-center justify-between">
          <h2 id="active-heading" className="text-base font-bold">
            Active jobs
          </h2>
          <Link to="/rider/history" className="text-sm font-semibold text-amber-700 hover:underline">
            Delivery history
          </Link>
        </div>
        {list}
      </section>
      <Money />
    </div>
  )
}

export function RiderHistoryPage() {
  usePageMeta('Delivery history')
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)
  const gate = useRider('/rider/history')
  const jobs = useJobs('history', page)
  if (gate) return gate

  let body
  if (jobs.isPending) body = <PageSpinner label="Loading history…" />
  else if (jobs.isError) body = <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} title="Couldn’t load your history" />
  else if (!jobs.data.results.length) body = <EmptyState title="No finished jobs yet">Completed, failed and rejected jobs appear here.</EmptyState>
  else
    body = (
      <>
        <ul className="space-y-3" aria-busy={jobs.isFetching}>
          {jobs.data.results.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </ul>
        <Pagination page={page} pageSize={JOBS_PAGE_SIZE} total={jobs.data.count} onChange={(p) => setParams(p > 1 ? { page: String(p) } : {})} />
      </>
    )

  return (
    <div className="container-page max-w-3xl py-6">
      <Breadcrumbs items={[{ label: 'Rider app', to: '/rider' }, { label: 'History' }]} />
      <h1 className="mb-4 mt-2 text-2xl font-bold">Delivery history</h1>
      {body}
    </div>
  )
}

function Notes({ job }: { job: Job }) {
  const save = useSaveNotes(job.id)
  const toast = useToast()
  const [notes, setNotes] = useState(job.delivery_notes)
  const editable = job.next_actions.length > 0

  function submit(event: FormEvent) {
    event.preventDefault()
    save.mutate(notes, {
      onSuccess: () => toast.show('Note saved'),
      onError: (error) => toast.show(error instanceof ApiError ? error.message : 'Could not save the note.', { tone: 'error' }),
    })
  }

  if (!editable) {
    return job.delivery_notes ? (
      <p className="rounded-lg bg-white p-4 text-sm ring-1 ring-steel-200">
        <span className="font-semibold">Your note: </span>
        {job.delivery_notes}
      </p>
    ) : null
  }
  return (
    <form onSubmit={submit} className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
      <label htmlFor="job-notes" className="label">
        Delivery note for the store <span className="font-normal text-ink-600">(optional)</span>
      </label>
      <textarea id="job-notes" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} rows={2} className="input" />
      <button type="submit" disabled={save.isPending || notes === job.delivery_notes} className="btn-secondary mt-2 px-3 py-1.5 text-sm">
        {save.isPending ? 'Saving…' : 'Save note'}
      </button>
    </form>
  )
}

const STEP_HELP: Partial<Record<Job['status'], { delivery: string; return_pickup: string }>> = {
  assigned: {
    delivery: 'Accept the job, then collect the order at the store.',
    return_pickup: 'Accept the job, then collect the items from the customer.',
  },
  accepted: {
    delivery: 'Go to the store and collect the packed order.',
    return_pickup: 'Go to the customer and collect the items listed below.',
  },
  picked_up: {
    delivery: 'You have the order. Start the delivery when you leave the store.',
    return_pickup: 'You have the items. Bring them to the store.',
  },
  out_for_delivery: {
    delivery: 'Go to the customer. Ask for the delivery code before handing over.',
    return_pickup: '',
  },
}

function Actions({ job }: { job: Job }) {
  const step = useJobStep(job.id)
  const toast = useToast()
  const [rejecting, setRejecting] = useState(false)
  const [failing, setFailing] = useState(false)
  const can = (action: Job['next_actions'][number]) => job.next_actions.includes(action)
  const run = (name: 'accept' | 'pickup' | 'start', done: string) =>
    step.mutate(name, {
      onSuccess: () => toast.show(done),
      onError: (error) => toast.show(error instanceof ApiError ? error.message : 'Could not save. Please try again.', { tone: 'error' }),
    })
  const pickup = job.kind === 'return_pickup'

  if (!job.next_actions.length) return null
  return (
    <section aria-label="What to do next" className="space-y-3">
      {STEP_HELP[job.status]?.[job.kind] && (
        <p role="status" className="rounded-lg bg-amber-100 px-4 py-3 text-sm font-medium text-ink-900">
          {STEP_HELP[job.status]![job.kind]}
        </p>
      )}
      {can('complete') ? (
        <CompleteDeliveryForm job={job} extra={can('proof') ? <ProofUpload job={job} /> : undefined} />
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row">
          {can('accept') && (
            <button type="button" onClick={() => run('accept', 'Job accepted')} disabled={step.isPending} className="btn-primary flex-1 py-3 text-base">
              {step.isPending ? 'Saving…' : 'Accept job'}
            </button>
          )}
          {can('pickup') && (
            <button
              type="button"
              onClick={() => run('pickup', pickup ? 'Items collected' : 'Order picked up')}
              disabled={step.isPending}
              className="btn-primary flex-1 py-3 text-base"
            >
              {step.isPending ? 'Saving…' : pickup ? 'I have collected the items' : 'I have picked up the order'}
            </button>
          )}
          {can('start') && (
            <button type="button" onClick={() => run('start', 'Delivery started')} disabled={step.isPending} className="btn-primary flex-1 py-3 text-base">
              {step.isPending ? 'Saving…' : 'Start delivery'}
            </button>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {can('reject') && (
          <button type="button" onClick={() => setRejecting(true)} className="font-semibold text-ink-800 underline">
            I can’t take this job
          </button>
        )}
        {can('fail') && (
          <button type="button" onClick={() => setFailing(true)} className="font-semibold text-danger-600 underline">
            {pickup ? 'Pickup not possible' : 'Delivery not possible'}
          </button>
        )}
      </div>
      <RejectDialog job={job} open={rejecting} onClose={() => setRejecting(false)} />
      <FailDialog job={job} open={failing} onClose={() => setFailing(false)} />
    </section>
  )
}

function Outcome({ job }: { job: Job }) {
  if (job.status === 'delivered') {
    return (
      <div role="status" className="rounded-lg bg-success-600/10 p-4 text-sm text-success-600">
        <p className="font-semibold">
          {job.kind === 'return_pickup' ? 'Handed over at the store' : 'Delivered'} {time(job.delivered_at)}
        </p>
        <p>You earned {formatPrice(job.earning_amount)} for this job.</p>
        {job.cod?.collected && (
          <p className="mt-1 text-ink-900">
            Collected {formatPrice(job.cod.collected_amount)} ({job.cod.method === 'upi' ? 'UPI' : 'cash'}).{' '}
            {job.cod.handed_over
              ? job.cod.method === 'upi'
                ? 'Paid directly to the store.'
                : `Handed over to the store ${time(job.cod.handed_over_at)}.`
              : 'Hand this cash over to the store.'}
          </p>
        )}
      </div>
    )
  }
  if (job.status === 'failed') {
    return (
      <div role="status" className="rounded-lg bg-danger-600/10 p-4 text-sm">
        <p className="font-semibold text-danger-600">Reported as failed {time(job.failed_at)}</p>
        <p className="text-ink-800">{job.failure_reason}</p>
      </div>
    )
  }
  if (job.status === 'rejected') {
    return (
      <p role="status" className="rounded-lg bg-steel-100 p-4 text-sm text-ink-800">
        You rejected this job: {job.reject_reason}
      </p>
    )
  }
  if (job.status === 'cancelled') {
    return (
      <p role="status" className="rounded-lg bg-steel-100 p-4 text-sm text-ink-800">
        The store took this job off your list. Nothing more to do.
      </p>
    )
  }
  return null
}

export function RiderJobPage() {
  const { id = '' } = useParams()
  const jobId = Number(id)
  usePageMeta(`Job ${id}`)
  const gate = useRider(`/rider/jobs/${id}`)
  const job = useJob(jobId)
  if (gate) return gate
  if (!Number.isInteger(jobId) || jobId < 1) return <NotFoundPage />
  if (job.isPending) return <PageSpinner label="Loading job…" />
  if (job.isError) {
    if (isNotFound(job.error)) return <NotFoundPage />
    return (
      <div className="container-page py-10">
        <ErrorState error={job.error} onRetry={() => job.refetch()} title="Couldn’t load this job" />
      </div>
    )
  }
  const data = job.data
  const pickup = data.kind === 'return_pickup'

  return (
    <div className="container-page max-w-3xl space-y-4 pb-10 pt-6">
      <Breadcrumbs items={[{ label: 'Rider app', to: '/rider' }, { label: data.order_number }]} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">
            {pickup ? 'Return pickup' : 'Delivery'} · {data.order_number}
          </h1>
          <p className="text-sm text-ink-600">
            Assigned {formatDate(data.assigned_at)}
            {data.distance_km && ` · about ${Number(data.distance_km).toFixed(1)} km`}
            {pickup && data.return_number && ` · return ${data.return_number}`}
          </p>
        </div>
        <JobStatusBadge job={data} />
      </div>

      {data.amount_to_collect && (
        <p className="rounded-lg bg-amber-100 px-4 py-3 text-sm text-ink-900">
          Cash on delivery: collect <span className="text-lg font-bold">{formatPrice(data.amount_to_collect)}</span>
        </p>
      )}
      {!data.amount_to_collect && data.kind === 'delivery' && data.next_actions.length > 0 && (
        <p className="rounded-lg bg-steel-100 px-4 py-3 text-sm text-ink-800">Already paid online. Do not collect money.</p>
      )}

      <Outcome job={data} />
      <Actions job={data} />
      <LocationCard title={pickup ? 'Collect from (customer)' : 'Collect from (store)'} place={data.pickup} callLabel={pickup ? 'Call customer' : 'Call store'} />
      <LocationCard title={pickup ? 'Bring to (store)' : 'Deliver to (customer)'} place={data.drop} callLabel={pickup ? 'Call store' : 'Call customer'} />
      <ItemList job={data} />
      <Notes key={data.delivery_notes} job={data} />

      <section aria-labelledby="job-history" className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
        <h2 id="job-history" className="text-xs font-bold uppercase tracking-wide text-ink-600">
          What happened
        </h2>
        <ol className="mt-1 space-y-1 text-sm">
          {data.status_history.map((entry) => (
            <li key={`${entry.to_status}-${entry.created_at}`} className="flex justify-between gap-3">
              <span>{entry.note || entry.to_status}</span>
              <span className="shrink-0 text-xs text-ink-600">{time(entry.created_at)}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
