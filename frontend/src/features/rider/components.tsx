import { useState, type FormEvent, type ReactNode } from 'react'

import { Modal } from '@/components/Modal'
import { PinIcon } from '@/components/icons'
import { useToast } from '@/components/toast'
import { ApiError } from '@/lib/api/errors'
import { formatPrice } from '@/lib/format'

import { useCompleteJob, useFailJob, useRejectJob, useUploadProof } from './api'
import type { CodMethod, FailureCode, Job, JobLocation, JobStatus } from './types'

const STATUS_CLASSES: Record<JobStatus, string> = {
  assigned: 'bg-amber-100 text-amber-700',
  accepted: 'bg-amber-100 text-ink-900',
  picked_up: 'bg-amber-100 text-ink-900',
  out_for_delivery: 'bg-amber-100 text-ink-900',
  delivered: 'bg-success-600/10 text-success-600',
  failed: 'bg-danger-600/10 text-danger-600',
  rejected: 'bg-steel-100 text-ink-800',
  cancelled: 'bg-steel-100 text-ink-800',
}

export function JobStatusBadge({ job }: { job: Pick<Job, 'status' | 'status_label'> }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_CLASSES[job.status]}`}>
      {job.status_label}
    </span>
  )
}

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

/** Address, phone and free navigation links (OpenStreetMap, or the phone's own maps app). */
export function LocationCard({ title, place, callLabel }: { title: string; place: JobLocation | null; callLabel: string }) {
  if (!place) return null
  const hidden = !place.address && !place.name
  return (
    <section aria-label={title} className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
      <h3 className="text-xs font-bold uppercase tracking-wide text-ink-600">{title}</h3>
      {hidden ? (
        <p className="mt-1 text-sm text-ink-800">
          {[place.area, place.city].filter(Boolean).join(', ') || 'Address hidden'}
          <span className="block text-xs text-ink-600">Contact details are shown only while the job is active.</span>
        </p>
      ) : (
        <>
          <address className="mt-1 text-sm not-italic">
            <span className="block font-semibold text-ink-900">{place.name}</span>
            <span className="block text-ink-800">{place.address}</span>
            {place.landmark && <span className="block text-ink-600">Near {place.landmark}</span>}
          </address>
          {place.note && (
            <p className="mt-2 rounded-md bg-amber-100 px-3 py-2 text-sm text-ink-900">
              <span className="font-semibold">Customer’s note: </span>
              {place.note}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {place.geo_uri && (
              <a href={place.geo_uri} className="btn-primary flex items-center gap-1.5 px-3 py-2 text-sm">
                <PinIcon className="size-4" />
                Navigate
              </a>
            )}
            {place.directions_url && (
              <a href={place.directions_url} target="_blank" rel="noreferrer" className="btn-secondary px-3 py-2 text-sm">
                Open map
              </a>
            )}
            {place.phone && (
              <a href={`tel:${place.phone}`} className="btn-secondary px-3 py-2 text-sm">
                {callLabel}
                <span className="sr-only"> on {place.phone}</span>
              </a>
            )}
          </div>
        </>
      )}
    </section>
  )
}

export function ItemList({ job }: { job: Job }) {
  const units = job.items.reduce((sum, item) => sum + item.quantity, 0)
  return (
    <section aria-label="Items" className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
      <h3 className="text-xs font-bold uppercase tracking-wide text-ink-600">
        {job.kind === 'return_pickup' ? 'Items to collect' : 'Items to deliver'} ({units})
      </h3>
      <ul className="mt-1 divide-y divide-steel-100 text-sm">
        {job.items.map((item) => (
          <li key={item.sku} className="flex justify-between gap-3 py-1.5">
            <span>
              {item.name}
              {item.variant && <span className="text-ink-600"> ({item.variant})</span>}
              <span className="block text-xs text-ink-600">SKU {item.sku}</span>
            </span>
            <span className="font-semibold">× {item.quantity}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function RejectDialog({ job, open, onClose }: { job: Job; open: boolean; onClose: () => void }) {
  const reject = useRejectJob(job.id)
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!reason.trim()) return setError('Tell the store why you can’t take this job.')
    setError('')
    try {
      await reject.mutateAsync(reason.trim())
      toast.show('Job rejected. The store will assign someone else.')
      onClose()
    } catch (err) {
      setError(message(err, 'Could not reject the job. Please try again.'))
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Reject this job?">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div>
          <label htmlFor="reject-reason" className="label">
            Reason
          </label>
          <input
            id="reject-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={255}
            className="input"
            placeholder="e.g. Vehicle problem"
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-danger-600">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">
            Keep job
          </button>
          <button type="submit" disabled={reject.isPending} className="btn-dark flex-1">
            {reject.isPending ? 'Rejecting…' : 'Reject job'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

const FAILURE_REASONS: { value: FailureCode; label: string }[] = [
  { value: 'customer_unavailable', label: 'Customer not available' },
  { value: 'wrong_address', label: 'Address wrong or not found' },
  { value: 'customer_refused', label: 'Customer refused the delivery' },
  { value: 'payment_not_ready', label: 'Customer could not pay' },
  { value: 'damaged', label: 'Goods damaged on the way' },
  { value: 'vehicle_problem', label: 'Vehicle breakdown or accident' },
  { value: 'other', label: 'Other' },
]

export function FailDialog({ job, open, onClose }: { job: Job; open: boolean; onClose: () => void }) {
  const fail = useFailJob(job.id)
  const toast = useToast()
  const [reason, setReason] = useState<FailureCode | ''>('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const pickup = job.kind === 'return_pickup'

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!reason) return setError('Choose a reason.')
    if (reason === 'other' && !note.trim()) return setError('Describe what happened.')
    setError('')
    try {
      await fail.mutateAsync({ reason, note: note.trim() })
      toast.show(pickup ? 'Pickup reported as failed.' : 'Delivery reported as failed. Bring the goods back to the store.')
      onClose()
    } catch (err) {
      setError(message(err, 'Could not save. Please try again.'))
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={pickup ? 'Pickup not possible?' : 'Delivery not possible?'}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {!pickup && <p className="text-sm text-ink-800">Bring the goods back to the store. The store will arrange another attempt.</p>}
        <fieldset>
          <legend className="label">What happened?</legend>
          <div className="space-y-1.5">
            {FAILURE_REASONS.filter((option) => !pickup || !['damaged', 'payment_not_ready'].includes(option.value)).map(
              (option) => (
                <label key={option.value} className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-2 text-sm hover:bg-steel-50">
                  <input
                    type="radio"
                    name="fail-reason"
                    value={option.value}
                    checked={reason === option.value}
                    onChange={() => setReason(option.value)}
                    className="size-4 accent-amber-600"
                  />
                  {option.label}
                </label>
              ),
            )}
          </div>
        </fieldset>
        <div>
          <label htmlFor="fail-note" className="label">
            Details {reason !== 'other' && <span className="font-normal text-ink-600">(optional)</span>}
          </label>
          <textarea id="fail-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={255} rows={2} className="input" />
        </div>
        {error && (
          <p role="alert" className="text-sm text-danger-600">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">
            Back
          </button>
          <button type="submit" disabled={fail.isPending} className="btn-dark flex-1">
            {fail.isPending ? 'Saving…' : 'Report failed'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Photo of the handover. The server strips the photo's metadata and stores it privately. */
export function ProofUpload({ job }: { job: Job }) {
  const upload = useUploadProof(job.id)
  const [error, setError] = useState('')

  async function choose(file: File | undefined) {
    if (!file) return
    setError('')
    if (file.size > 8 * 1024 * 1024) return setError('The photo is too large (8 MB at most).')
    try {
      await upload.mutateAsync({ photo: file, receivedBy: '' })
    } catch (err) {
      setError(message(err, 'Could not upload the photo. Please try again.'))
    }
  }

  return (
    <div>
      <label htmlFor="proof-photo" className="label">
        Photo of the {job.kind === 'return_pickup' ? 'collected items' : 'delivery'}{' '}
        <span className="font-normal text-ink-600">{job.proof_required ? '(required)' : '(optional)'}</span>
      </label>
      <input
        id="proof-photo"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        disabled={upload.isPending}
        onChange={(e) => void choose(e.target.files?.[0])}
        className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-steel-100 file:px-3 file:py-2 file:font-semibold"
      />
      <p role="status" className="mt-1 text-xs text-ink-600">
        {upload.isPending ? 'Uploading…' : job.proof_uploaded ? 'Photo saved. Choose another to replace it.' : 'No photo yet.'}
      </p>
      {error && (
        <p role="alert" className="mt-1 text-xs text-danger-600">
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Handover at the door: the customer's code, the cash for cash-on-delivery orders, who
 * received it. The server checks all of it; a wrong code or amount completes nothing.
 */
export function CompleteDeliveryForm({ job, extra }: { job: Job; extra?: ReactNode }) {
  const complete = useCompleteJob(job.id)
  const toast = useToast()
  const [otp, setOtp] = useState('')
  const [collected, setCollected] = useState(false)
  const [method, setMethod] = useState<CodMethod>('cash')
  const [reference, setReference] = useState('')
  const [receivedBy, setReceivedBy] = useState(job.received_by)
  const [error, setError] = useState('')
  const due = job.amount_to_collect
  const needsCode = job.kind === 'delivery'

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (needsCode && otp.length !== 6) return setError('Enter the 6-digit code from the customer.')
    if (due && !collected) return setError(`Collect ${formatPrice(due)} from the customer and tick the box.`)
    if (job.proof_required && !job.proof_uploaded) return setError('Take a photo of the delivery first.')
    setError('')
    try {
      await complete.mutateAsync({
        ...(needsCode ? { otp } : {}),
        ...(due ? { cod_collected: true, cod_amount: due, cod_method: method, cod_reference: reference.trim() } : {}),
        received_by: receivedBy.trim(),
      })
      toast.show(needsCode ? 'Delivered. Well done!' : 'Return handed over at the store.')
    } catch (err) {
      setOtp('')
      setError(message(err, 'Could not complete. Please try again.'))
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg bg-white p-4 ring-1 ring-steel-200" noValidate>
      <h3 className="text-base font-bold">{needsCode ? 'Complete the delivery' : 'Hand over at the store'}</h3>
      {needsCode && (
        <div>
          <label htmlFor="delivery-otp" className="label">
            Delivery code from the customer
          </label>
          <input
            id="delivery-otp"
            value={otp}
            onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            className="input font-mono text-2xl tracking-[0.3em]"
            aria-describedby="delivery-otp-hint"
            placeholder="••••••"
          />
          <p id="delivery-otp-hint" className="mt-1 text-xs text-ink-600">
            {job.otp_state === 'locked'
              ? 'The code is blocked after too many wrong tries. Ask the customer to get a new code on their order page.'
              : job.otp_state === 'expired'
                ? 'The code has expired. Ask the customer to get a new code on their order page.'
                : 'The customer sees it on their order page. Hand over only after the code is accepted.'}
          </p>
        </div>
      )}
      {due && (
        <fieldset className="rounded-md bg-amber-100 p-3">
          <legend className="sr-only">Cash on delivery</legend>
          <p className="text-sm font-semibold text-ink-900">
            Collect <span className="text-lg">{formatPrice(due)}</span> from the customer
          </p>
          <div className="mt-2 flex gap-4 text-sm">
            {(['cash', 'upi'] as const).map((option) => (
              <label key={option} className="flex min-h-10 cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="cod-method"
                  value={option}
                  checked={method === option}
                  onChange={() => setMethod(option)}
                  className="size-4 accent-amber-600"
                />
                {option === 'cash' ? 'Cash' : 'UPI to the store'}
              </label>
            ))}
          </div>
          {method === 'upi' && (
            <div className="mt-2">
              <label htmlFor="cod-reference" className="label">
                UPI reference <span className="font-normal text-ink-600">(optional)</span>
              </label>
              <input id="cod-reference" value={reference} onChange={(e) => setReference(e.target.value)} maxLength={60} className="input" />
            </div>
          )}
          <label className="mt-2 flex min-h-10 cursor-pointer items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={collected} onChange={(e) => setCollected(e.target.checked)} className="size-5 accent-amber-600" />I
            have received {formatPrice(due)}
          </label>
        </fieldset>
      )}
      <div>
        <label htmlFor="received-by" className="label">
          Received by <span className="font-normal text-ink-600">(optional)</span>
        </label>
        <input
          id="received-by"
          value={receivedBy}
          onChange={(e) => setReceivedBy(e.target.value)}
          maxLength={120}
          className="input"
          placeholder={needsCode ? 'e.g. the customer, a family member' : 'Store staff name'}
        />
      </div>
      {extra}
      {error && (
        <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
          {error}
        </p>
      )}
      <button type="submit" disabled={complete.isPending} className="btn-primary w-full py-3 text-base">
        {complete.isPending ? 'Checking…' : needsCode ? 'Complete delivery' : 'Handed over at the store'}
      </button>
    </form>
  )
}
