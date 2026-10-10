import { useState } from 'react'
import { Link, useLocation } from 'react-router'

import { useAuth } from '@/features/auth/context'
import { ApiError } from '@/lib/api/errors'

import { useProductEnquiry } from './api'
import { whatsappLink } from './whatsapp'

/**
 * "Ask about this product": a signed-in customer's question goes to the shop's support inbox,
 * linked to the product; the reply arrives in notifications (and on WhatsApp when they opted in).
 * "Chat on WhatsApp" opens the shop's number with the product prefilled, when one is configured.
 */
export function ProductEnquiry({ productId, productName }: { productId: number; productName: string }) {
  const { status } = useAuth()
  const location = useLocation()
  const enquiry = useProductEnquiry()
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const productUrl = typeof window === 'undefined' ? location.pathname : window.location.origin + location.pathname
  const whatsapp = whatsappLink(productName, productUrl)
  const next = encodeURIComponent(location.pathname + location.search)

  return (
    <section aria-labelledby="product-enquiry-heading" className="space-y-3 rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
      <h2 id="product-enquiry-heading" className="text-sm font-bold text-ink-950">
        Have a question about this product?
      </h2>
      {enquiry.isSuccess ? (
        <p role="status" className="text-sm text-success-600">
          Thanks! Your question was sent to our team. We’ll reply in your{' '}
          <Link to="/notifications" className="font-semibold underline">
            notifications
          </Link>
          .
        </p>
      ) : status !== 'authenticated' ? (
        <p className="text-sm text-ink-800">
          <Link to={`/login?next=${next}`} className="font-semibold text-amber-700 hover:underline">
            Sign in
          </Link>{' '}
          to ask our team about it.
        </p>
      ) : open ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault()
            if (!message.trim()) return
            enquiry.mutate({ productId, message: message.trim() })
          }}
        >
          <label htmlFor="product-enquiry-message" className="label">
            Your question
          </label>
          <textarea
            id="product-enquiry-message"
            className="input min-h-24"
            maxLength={2000}
            required
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="e.g. Is this suitable for outdoor use?"
          />
          {enquiry.isError && (
            <p role="alert" className="text-xs text-danger-600">
              {enquiry.error instanceof ApiError ? enquiry.error.message : 'Your question couldn’t be sent. Please try again.'}
            </p>
          )}
          <div className="flex gap-2">
            <button type="submit" className="btn-primary" disabled={enquiry.isPending || !message.trim()}>
              {enquiry.isPending ? 'Sending…' : 'Send question'}
            </button>
            <button type="button" className="btn-secondary" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="btn-secondary" onClick={() => setOpen(true)}>
          Ask about this product
        </button>
      )}
      {whatsapp && (
        <a href={whatsapp} target="_blank" rel="noreferrer" className="inline-block text-sm font-semibold text-amber-700 hover:underline">
          Chat on WhatsApp
        </a>
      )}
    </section>
  )
}
