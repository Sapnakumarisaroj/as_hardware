import { Link, useLocation } from 'react-router'

import { business } from '@/lib/business'

import { whatsappUrl } from './order'

/** The WhatsApp glyph (brand mark, drawn inline; no external assets). */
export function WhatsAppIcon({ className = 'size-6' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className} fill="currentColor">
      <path d="M16.04 3C9.4 3 4 8.36 4 14.96c0 2.1.56 4.15 1.62 5.95L4 29l8.3-1.57a12.1 12.1 0 0 0 3.74.6C22.68 28.03 28 22.67 28 16.07 28 9.47 22.68 3 16.04 3Zm0 22.86c-1.18 0-2.34-.2-3.43-.6l-.48-.17-4.93.93.95-4.75-.2-.5a9.67 9.67 0 0 1-1.42-5.06c0-5.38 4.17-9.8 9.5-9.8 5.33 0 9.67 4.4 9.67 9.8 0 5.38-4.34 10.15-9.66 10.15Zm5.3-7.25c-.29-.15-1.72-.85-1.99-.94-.27-.1-.46-.15-.66.15-.19.29-.75.94-.92 1.13-.17.2-.34.22-.63.08-.29-.15-1.22-.45-2.33-1.43a8.7 8.7 0 0 1-1.61-2c-.17-.29-.02-.45.13-.6.13-.13.29-.34.44-.5.14-.18.19-.3.29-.5.1-.19.05-.36-.03-.5-.07-.15-.65-1.57-.9-2.15-.23-.56-.47-.48-.65-.49h-.55c-.2 0-.51.07-.78.36-.27.3-1.02 1-1.02 2.42 0 1.43 1.05 2.82 1.2 3.01.14.2 2.06 3.14 5 4.4.7.3 1.24.48 1.67.62.7.22 1.34.19 1.84.12.56-.08 1.72-.7 1.96-1.38.25-.68.25-1.26.17-1.38-.07-.12-.26-.2-.55-.34Z" />
    </svg>
  )
}

const GREETING = `Hello ${business.name}, I would like to order some hardware.`

/**
 * Floating click-to-chat button, bottom-right on every customer page. On the cart and checkout it sits
 * above their sticky mobile action bar so it never covers "Place order".
 */
export function WhatsAppFloat() {
  const { pathname } = useLocation()
  const raised = pathname.startsWith('/cart') || pathname.startsWith('/checkout')
  return (
    <a
      href={whatsappUrl(GREETING)}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Chat with us on WhatsApp (opens WhatsApp)"
      title="Chat on WhatsApp"
      data-testid="whatsapp-float"
      className={`fixed right-4 z-30 grid size-14 place-items-center rounded-full bg-[#25D366] text-white shadow-lg shadow-ink-950/20 ring-4 ring-white transition hover:scale-105 hover:bg-[#1ebe5b] focus-visible:outline-none focus-visible:ring-amber-400 sm:right-6 ${
        raised ? 'bottom-24 lg:bottom-6' : 'bottom-5 sm:bottom-6'
      }`}
    >
      <WhatsAppIcon className="size-8" />
    </a>
  )
}

/** "Order on WhatsApp": opens the order form, prefilled from the cart or with one product. */
export function OrderOnWhatsAppButton({
  from,
  product,
  quantity,
  className = '',
}: {
  from?: 'cart'
  product?: string
  quantity?: number
  className?: string
}) {
  const params = new URLSearchParams()
  if (from) params.set('from', from)
  if (product) params.set('product', product)
  if (product && quantity) params.set('qty', String(quantity))
  return (
    <Link
      to={`/order-on-whatsapp${params.size ? `?${params}` : ''}`}
      className={`inline-flex items-center justify-center gap-2 rounded-lg bg-[#25D366] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#1ebe5b] active:translate-y-px ${className}`}
    >
      <WhatsAppIcon className="size-5" />
      Order on WhatsApp
    </Link>
  )
}
