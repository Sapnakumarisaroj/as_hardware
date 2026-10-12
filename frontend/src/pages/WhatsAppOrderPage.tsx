import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'

import { useAuth } from '@/features/auth/context'
import { useCart, type Cart } from '@/features/cart/api'
import { useProducts } from '@/features/catalog/api'
import { WhatsAppIcon } from '@/features/whatsapp/components'
import {
  MAX_QUANTITY,
  WHATSAPP_DISPLAY,
  hasErrors,
  money,
  orderMessage,
  validateOrder,
  whatsappUrl,
  type OrderErrors,
  type OrderForm,
  type OrderLine,
} from '@/features/whatsapp/order'
import { usePageMeta } from '@/lib/usePageMeta'

const EMPTY_LINE: OrderLine = { name: '', quantity: '1' }

function cartLines(cart: Cart): OrderLine[] {
  return cart.items.map((item) => ({
    name: item.variant_name ? `${item.product_name} (${item.variant_name})` : item.product_name,
    quantity: String(item.quantity),
    unitPrice: money(item.unit_price),
    lineTotal: money(item.line_total),
  }))
}

function useDebounced(value: string, ms = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(timer)
  }, [value, ms])
  return debounced
}

/** Product name with suggestions from the catalogue (typing anything else is fine too). */
function ProductNameInput({ id, value, onChange, error }: { id: string; value: string; onChange: (v: string) => void; error?: string }) {
  const query = useDebounced(value.trim())
  const suggestions = useProducts({ q: query, page_size: '6' }, { enabled: query.length >= 2 })
  const listId = `${id}-suggestions`
  return (
    <>
      <input
        id={id}
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        placeholder="e.g. Hettich soft close hinge"
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`input ${error ? 'border-danger-600' : ''}`}
      />
      <datalist id={listId}>
        {(suggestions.data?.results ?? []).map((p) => (
          <option key={p.id} value={p.name} />
        ))}
      </datalist>
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs font-medium text-danger-600">
          {error}
        </p>
      )}
    </>
  )
}

function Field({ id, label, error, optional, children }: { id: string; label: string; error?: string; optional?: boolean; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="label">
        {label} {optional && <span className="font-normal text-ink-600">(optional)</span>}
      </label>
      {children}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs font-medium text-danger-600">
          {error}
        </p>
      )}
    </div>
  )
}

/** "Order Hardware & Plywood on WhatsApp": a form that opens WhatsApp with the order written out. */
export function WhatsAppOrderPage() {
  usePageMeta('Order on WhatsApp')
  const [params] = useSearchParams()
  const { status } = useAuth()
  const cart = useCart()
  const uid = useId()
  const fromCart = params.get('from') === 'cart'
  const productParam = params.get('product') ?? ''
  const qtyParam = params.get('qty') ?? '1'
  const [form, setForm] = useState<OrderForm>(() => ({
    name: '',
    mobile: '',
    address: '',
    area: '',
    instructions: '',
    lines: productParam ? [{ name: productParam, quantity: /^\d+$/.test(qtyParam) ? qtyParam : '1' }] : [{ ...EMPTY_LINE }],
  }))
  const [errors, setErrors] = useState<OrderErrors>({})
  const [opened, setOpened] = useState(false)
  const [cartApplied, setCartApplied] = useState(false)
  const cartItems = cart.data?.items ?? []

  // Opened from the cart: bring every cart item and quantity (with website prices) in once, as soon as
  // the cart has loaded (set during render, as elsewhere in the app, instead of in an effect).
  if (fromCart && !cartApplied && cart.data && cart.data.items.length) {
    setCartApplied(true)
    setForm((f) => ({ ...f, lines: cartLines(cart.data!), subtotal: money(cart.data!.totals.subtotal) }))
  }

  const set = (key: 'name' | 'mobile' | 'address' | 'area' | 'instructions') => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }))
  // Any edit of the product list means the website subtotal no longer describes it.
  const setLines = (lines: OrderLine[]) => setForm((f) => ({ ...f, lines, subtotal: undefined }))
  const setLine = (index: number, patch: Partial<OrderLine>) =>
    setLines(form.lines.map((l, i) => (i === index ? { ...l, ...patch, unitPrice: undefined, lineTotal: undefined } : l)))

  function addCartItems() {
    if (!cart.data) return
    const existing = form.lines.filter((l) => l.name.trim())
    setForm((f) => ({
      ...f,
      lines: existing.length ? [...existing, ...cartLines(cart.data!)] : cartLines(cart.data!),
      subtotal: existing.length ? undefined : money(cart.data!.totals.subtotal),
    }))
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const found = validateOrder(form)
    setErrors(found)
    if (hasErrors(found)) {
      document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
      return
    }
    window.open(whatsappUrl(orderMessage(form)), '_blank', 'noopener,noreferrer')
    setOpened(true)
  }

  const id = (name: string) => `${uid}-${name}`
  return (
    <div className="container-page py-8 sm:py-10">
      <div className="mx-auto max-w-3xl">
        <header className="mb-6 text-center">
          <span aria-hidden className="mx-auto mb-3 grid size-14 place-items-center rounded-full bg-[#25D366] text-white">
            <WhatsAppIcon className="size-8" />
          </span>
          <h1 className="text-2xl font-extrabold tracking-tight text-ink-950 sm:text-3xl">Order Hardware &amp; Plywood on WhatsApp</h1>
          <p className="mx-auto mt-2 max-w-xl text-ink-600">
            Share your requirements and delivery address. Our team will contact you to confirm your order.
          </p>
        </header>

        {opened && (
          <div role="status" className="mb-5 rounded-xl bg-success-600/10 px-4 py-3 text-sm text-ink-900 ring-1 ring-success-600/30">
            <p className="font-semibold">WhatsApp opened with your order details — please press Send in WhatsApp.</p>
            <p className="mt-1">
              Your order is <strong>not confirmed yet</strong>. Our team will reply on WhatsApp ({WHATSAPP_DISPLAY}) to confirm
              availability, the final price, delivery charges and the delivery time. Nothing has been charged.
            </p>
          </div>
        )}

        <form onSubmit={submit} noValidate className="card space-y-6 p-5 sm:p-8" aria-label="Order on WhatsApp">
          <fieldset className="grid gap-4 sm:grid-cols-2">
            <legend className="mb-3 text-base font-bold text-ink-950">Your details</legend>
            <Field id={id('name')} label="Customer name" error={errors.name}>
              <input id={id('name')} className="input" autoComplete="name" value={form.name} onChange={(e) => set('name')(e.target.value)}
                aria-invalid={Boolean(errors.name)} aria-describedby={errors.name ? `${id('name')}-error` : undefined} />
            </Field>
            <Field id={id('mobile')} label="Mobile number" error={errors.mobile}>
              <div className="flex gap-2">
                <span className="input flex h-auto w-auto shrink-0 items-center bg-steel-50 text-ink-700">+91</span>
                <input id={id('mobile')} className="input min-w-0 flex-1" type="tel" inputMode="numeric" autoComplete="tel-national"
                  placeholder="98765 43210" value={form.mobile} onChange={(e) => set('mobile')(e.target.value)}
                  aria-invalid={Boolean(errors.mobile)} aria-describedby={errors.mobile ? `${id('mobile')}-error` : undefined} />
              </div>
            </Field>
          </fieldset>

          <fieldset>
            <legend className="mb-3 text-base font-bold text-ink-950">Products</legend>
            {cartItems.length > 0 && !cartApplied && (
              <button type="button" onClick={() => { addCartItems(); setCartApplied(true) }}
                className="btn-secondary mb-3 w-full sm:w-auto">
                Add the {cartItems.length} item{cartItems.length === 1 ? '' : 's'} from my cart
              </button>
            )}
            {status !== 'authenticated' && fromCart && (
              <p className="mb-3 text-sm text-ink-600">Sign in to bring your cart items here, or type the products below.</p>
            )}
            {errors.lines && <p role="alert" className="mb-2 text-sm font-medium text-danger-600">{errors.lines}</p>}
            <ol className="space-y-3">
              {form.lines.map((line, index) => {
                const lineErrors = errors.line?.[index]
                return (
                  <li key={index} className="grid grid-cols-[1fr_6.5rem] gap-2 rounded-xl bg-steel-50 p-3 ring-1 ring-steel-200 sm:grid-cols-[1fr_7rem_auto] sm:items-start">
                    <div className="col-span-2 sm:col-span-1">
                      <label htmlFor={id(`product-${index}`)} className="label">
                        Product {index + 1}
                      </label>
                      <ProductNameInput id={id(`product-${index}`)} value={line.name} onChange={(name) => setLine(index, { name })} error={lineErrors?.name} />
                      {line.lineTotal && (
                        <p className="mt-1 text-xs text-ink-600">
                          Website price: {line.unitPrice} each · {line.lineTotal}
                        </p>
                      )}
                    </div>
                    <div>
                      <label htmlFor={id(`qty-${index}`)} className="label">
                        Quantity
                      </label>
                      <input id={id(`qty-${index}`)} className={`input ${lineErrors?.quantity ? 'border-danger-600' : ''}`} type="number" min={1}
                        max={MAX_QUANTITY} step={1} inputMode="numeric" value={line.quantity}
                        onChange={(e) => setLine(index, { quantity: e.target.value })}
                        aria-invalid={Boolean(lineErrors?.quantity)} aria-describedby={lineErrors?.quantity ? `${id(`qty-${index}`)}-error` : undefined} />
                      {lineErrors?.quantity && (
                        <p id={`${id(`qty-${index}`)}-error`} className="mt-1 text-xs font-medium text-danger-600">{lineErrors.quantity}</p>
                      )}
                    </div>
                    {form.lines.length > 1 && (
                      <button type="button" onClick={() => setLines(form.lines.filter((_, i) => i !== index))}
                        className="self-end justify-self-end rounded-md px-2 py-2 text-sm font-semibold text-danger-600 hover:bg-white sm:mt-7">
                        Remove <span className="sr-only">product {index + 1}</span>
                      </button>
                    )}
                  </li>
                )
              })}
            </ol>
            <button type="button" onClick={() => setLines([...form.lines, { ...EMPTY_LINE }])} className="btn-secondary mt-3">
              + Add Product
            </button>
            {form.subtotal && (
              <p className="mt-3 text-sm text-ink-700">
                Estimated subtotal from your cart: <span className="font-semibold">{form.subtotal}</span> (website prices, before
                delivery; the shop confirms the final price).
              </p>
            )}
          </fieldset>

          <fieldset className="grid gap-4">
            <legend className="mb-3 text-base font-bold text-ink-950">Delivery</legend>
            <Field id={id('address')} label="Delivery address" error={errors.address}>
              <textarea id={id('address')} className="input min-h-20" autoComplete="street-address" placeholder="House / building, street, landmark"
                value={form.address} onChange={(e) => set('address')(e.target.value)}
                aria-invalid={Boolean(errors.address)} aria-describedby={errors.address ? `${id('address')}-error` : undefined} />
            </Field>
            <Field id={id('area')} label="Area / locality in Bengaluru" error={errors.area}>
              <input id={id('area')} className="input" autoComplete="address-level3" placeholder="e.g. Kalkere, Horamavu"
                value={form.area} onChange={(e) => set('area')(e.target.value)}
                aria-invalid={Boolean(errors.area)} aria-describedby={errors.area ? `${id('area')}-error` : undefined} />
            </Field>
            <Field id={id('instructions')} label="Delivery instructions" optional>
              <textarea id={id('instructions')} className="input min-h-16" maxLength={300} placeholder="e.g. Call before delivery, 2nd floor"
                value={form.instructions} onChange={(e) => set('instructions')(e.target.value)} />
            </Field>
          </fieldset>

          <div className="space-y-3 border-t border-steel-200 pt-5">
            <p className="text-xs text-ink-600">
              This opens WhatsApp with your order written out; it does not place, confirm or charge an order. Our team confirms
              availability, the final price, delivery charges and the delivery time on WhatsApp. Never share OTPs or card details
              in the chat.
            </p>
            <button type="submit" className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-[#25D366] text-base font-bold text-white transition hover:bg-[#1ebe5b] active:translate-y-px">
              <WhatsAppIcon className="size-6" />
              Send order on WhatsApp
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
