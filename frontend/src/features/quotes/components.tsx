import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { Modal } from '@/components/Modal'
import { useToast } from '@/components/toast'

import { quoteErrorMessage, useRequestQuote, type Quote, type QuoteStatus } from './api'

const TONE: Record<QuoteStatus, string> = {
  requested: 'bg-steel-100 text-ink-800',
  quoted: 'bg-amber-100 text-ink-900',
  accepted: 'bg-success-600/10 text-success-600',
  ordered: 'bg-success-600/10 text-success-600',
  cancelled: 'bg-steel-100 text-ink-600',
  declined: 'bg-steel-100 text-ink-600',
  rejected: 'bg-danger-600/10 text-danger-600',
  expired: 'bg-steel-100 text-ink-600',
}

export function QuoteStatusBadge({ quote }: { quote: Pick<Quote, 'status' | 'status_label'> }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ${TONE[quote.status]}`}>{quote.status_label}</span>
}

/**
 * "Request a bulk quote" for everything in the cart. The cart itself is left alone; the shop
 * replies with a quotation the customer can accept and order.
 */
export function RequestQuoteButton({ className = 'btn-secondary w-full' }: { className?: string }) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const request = useRequestQuote()
  const navigate = useNavigate()
  const toast = useToast()

  function submit(event: FormEvent) {
    event.preventDefault()
    request.mutate(
      { from_cart: true, note: note.trim() },
      {
        onSuccess: (quote) => {
          setOpen(false)
          toast.show(`Quote request ${quote.number} sent`)
          navigate(`/account/quotes/${quote.id}`)
        },
      },
    )
  }

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={className}>
        Request a bulk quote
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title="Request a bulk quote">
        <form onSubmit={submit} className="space-y-3 text-sm">
          <p className="text-ink-800">
            We’ll send you a price for every item in your cart at these quantities. Your cart stays as it is. Prices on a
            quotation include GST and are never above the MRP.
          </p>
          <div>
            <label htmlFor="quote-note" className="label">
              Note for the shop <span className="font-normal text-ink-600">(optional)</span>
            </label>
            <textarea
              id="quote-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              rows={3}
              className="input"
              placeholder="e.g. Site in Whitefield, delivery in two lots"
            />
          </div>
          {request.isError && (
            <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-danger-600">
              {quoteErrorMessage(request.error, 'Could not send the request. Please try again.')}
            </p>
          )}
          <div className="flex gap-2">
            <button type="button" onClick={() => setOpen(false)} className="btn-secondary flex-1">
              Cancel
            </button>
            <button type="submit" disabled={request.isPending} className="btn-primary flex-1">
              {request.isPending ? 'Sending…' : 'Send request'}
            </button>
          </div>
        </form>
      </Modal>
    </>
  )
}
