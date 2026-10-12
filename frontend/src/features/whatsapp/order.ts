import { validatePhone, normalizePhone } from '@/features/auth/validation'
import { business } from '@/lib/business'
import { env } from '@/lib/env'
import { formatPrice } from '@/lib/format'

/**
 * Ordering on WhatsApp with the free click-to-chat link (https://wa.me/<number>?text=…): no API, no keys.
 * Opening WhatsApp only prepares a message; the shop confirms availability, price, delivery and ETA in the
 * chat. Nothing here creates, confirms or pays for an order.
 */
const DEFAULT_NUMBER = '917338192616' // +91 73381 92616, the shop's WhatsApp
export const WHATSAPP_NUMBER = env.supportWhatsApp.replace(/\D/g, '') || DEFAULT_NUMBER
export const WHATSAPP_DISPLAY = `+${WHATSAPP_NUMBER.slice(0, 2)} ${WHATSAPP_NUMBER.slice(2)}`
export const MAX_QUANTITY = 9999

export function whatsappUrl(text: string): string {
  return `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(text)}`
}

/** A product line; price fields only when they come from the current cart / product data. */
export interface OrderLine {
  name: string
  quantity: string
  /** e.g. "₹2,662.85" per unit (current price on the website), optional. */
  unitPrice?: string
  lineTotal?: string
}

export interface OrderForm {
  name: string
  mobile: string
  address: string
  area: string
  instructions: string
  lines: OrderLine[]
  /** Estimated subtotal from the website cart, when the lines came from it unchanged. */
  subtotal?: string
}

export type OrderErrors = Partial<Record<'name' | 'mobile' | 'address' | 'area' | 'lines', string>> & {
  line?: Record<number, { name?: string; quantity?: string }>
}

export function validateOrder(form: OrderForm): OrderErrors {
  const errors: OrderErrors = {}
  if (form.name.trim().length < 2) errors.name = 'Enter your name.'
  const phone = validatePhone(form.mobile)
  if (phone) errors.mobile = phone
  if (form.address.trim().length < 10) errors.address = 'Enter the full delivery address (house/building, street).'
  if (form.area.trim().length < 2) errors.area = 'Enter your area or locality in Bengaluru.'
  const line: NonNullable<OrderErrors['line']> = {}
  const filled = form.lines.filter((l) => l.name.trim() || l.quantity.trim())
  if (!filled.length) errors.lines = 'Add at least one product.'
  form.lines.forEach((l, index) => {
    if (!l.name.trim() && !l.quantity.trim()) return
    const issue: { name?: string; quantity?: string } = {}
    if (!l.name.trim()) issue.name = 'Enter the product name.'
    const qty = Number(l.quantity)
    if (!/^\d+$/.test(l.quantity.trim()) || qty < 1) issue.quantity = 'Enter a quantity of 1 or more.'
    else if (qty > MAX_QUANTITY) issue.quantity = `At most ${MAX_QUANTITY}.`
    if (issue.name || issue.quantity) line[index] = issue
  })
  if (Object.keys(line).length) errors.line = line
  return errors
}

export function hasErrors(errors: OrderErrors): boolean {
  return Object.keys(errors).length > 0
}

/** The message, in the shop's agreed format (readable on a phone). */
export function orderMessage(form: OrderForm): string {
  const lines = form.lines.filter((l) => l.name.trim())
  const products = lines.map((l, i) => {
    const price = l.lineTotal ? ` (${l.unitPrice ? `${l.unitPrice} each, ` : ''}${l.lineTotal} on the website)` : ''
    return `${i + 1}. ${l.name.trim()} × ${Number(l.quantity)}${price}`
  })
  const parts = [
    `Hello ${business.name},`,
    '',
    'I would like to place a hardware order.',
    '',
    `Customer Name: ${form.name.trim()}`,
    `Mobile: +91 ${normalizePhone(form.mobile)}`,
    `Delivery Address: ${form.address.trim().replace(/\s*\n\s*/g, ', ')}`,
    `Area: ${form.area.trim()}`,
    '',
    'Products:',
    ...products,
  ]
  if (form.subtotal) parts.push('', `Estimated subtotal (website prices, before delivery): ${form.subtotal}`)
  if (form.instructions.trim()) parts.push('', `Delivery Instructions: ${form.instructions.trim()}`)
  parts.push(
    '',
    'Please confirm product availability, total price, delivery charges, and estimated delivery time.',
    '',
    'Thank you.',
  )
  return parts.join('\n')
}

export const money = (value: string | null | undefined) => (value ? formatPrice(value) : undefined)
