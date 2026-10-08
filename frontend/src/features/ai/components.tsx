import { Link } from 'react-router'

import { VerdictBadge } from '@/features/compatibility/components'

import { SparkIcon } from '@/components/icons'
import { useToast } from '@/components/toast'
import { AddToCartButton } from '@/features/cart/AddToCartButton'
import { useAddToCart } from '@/features/cart/api'
import { PriceBlock, StockLabel } from '@/features/catalog/components/badges'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { ApiError } from '@/lib/api/errors'

import type { AssistantMessage, RecommendedProduct } from './types'

/** A compact, touch-friendly card for a product the assistant found. Everything shown is the catalogue row. */
export function RecommendationCard({ product }: { product: RecommendedProduct }) {
  const href = `/p/${product.slug}`
  const outOfStock = product.stock_status === 'out_of_stock'
  const variantId = product.variant_id ?? product.default_variant_id
  return (
    <li className="flex gap-3 rounded-2xl bg-white shadow-(--shadow-card) p-3 ring-1 ring-steel-200">
      <Link to={href} tabIndex={-1} aria-hidden="true" className="shrink-0">
        <ProductImage src={product.image} alt={product.image_alt} className="size-20 rounded" />
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {product.brand && <p className="text-xs font-medium uppercase tracking-wide text-ink-600">{product.brand.name}</p>}
        <h3 className="text-sm font-semibold leading-snug">
          <Link to={href} className="hover:text-amber-700">
            {product.name}
          </Link>
        </h3>
        {product.reason && <p className="text-xs text-ink-600">{product.reason}</p>}
        <PriceBlock price={product.price} mrp={product.mrp} discountPercent={product.discount_percent} />
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <StockLabel status={product.stock_status} />
          {product.fast_delivery && !outOfStock && <span className="font-semibold text-success-600">Fast delivery</span>}
        </div>
        <div className="mt-1 flex flex-wrap gap-2">
          {outOfStock || !variantId ? (
            <button type="button" disabled className="btn-secondary px-3 py-1.5">
              Out of stock
            </button>
          ) : (
            <AddToCartButton variantId={variantId} productName={product.name} className="btn-primary px-3 py-1.5" />
          )}
          <Link to={href} className="btn-secondary px-3 py-1.5">
            View product
          </Link>
        </div>
      </div>
    </li>
  )
}

/** Adds every recommended item, one cart call each (the cart API validates each line). */
export function AddAllButton({ label, variantIds }: { label: string; variantIds: number[] }) {
  const addToCart = useAddToCart()
  const toast = useToast()
  async function addAll() {
    let added = 0
    for (const variantId of variantIds) {
      try {
        await addToCart.mutateAsync({ variantId, quantity: 1 })
        added += 1
      } catch (error) {
        toast.show(error instanceof ApiError ? error.message : 'Could not add one of the items.', { tone: 'error' })
      }
    }
    if (added > 0) toast.show(`Added ${added} ${added === 1 ? 'item' : 'items'} to your cart.`, { action: { label: 'View cart', to: '/cart' } })
  }
  return (
    <button type="button" className="btn-dark" disabled={addToCart.isPending} onClick={() => void addAll()}>
      {addToCart.isPending ? 'Adding…' : label}
    </button>
  )
}

function Paragraphs({ text }: { text: string }) {
  return (
    <>
      {text
        .split(/\n{2,}/)
        .filter(Boolean)
        .map((paragraph, index) => (
          <p key={index} className="whitespace-pre-wrap break-words">
            {paragraph}
          </p>
        ))}
    </>
  )
}

export function MessageBubble({
  message,
  signedIn,
  onSuggest,
}: {
  message: AssistantMessage
  signedIn: boolean
  onSuggest: (text: string) => void
}) {
  if (message.role === 'user') {
    return (
      <li className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-ink-900 px-4 py-2.5 text-sm text-white">
          <span className="sr-only">You: </span>
          <Paragraphs text={message.content} />
        </div>
      </li>
    )
  }
  const addAll = message.actions.find((action) => action.type === 'add_all')
  return (
    <li className="flex justify-start">
      <div className="max-w-[95%] space-y-3 sm:max-w-[85%]">
        <div className="space-y-2 rounded-2xl rounded-bl-sm bg-white px-4 py-3 text-sm ring-1 ring-steel-200">
          <span className="sr-only">Assistant: </span>
          <Paragraphs text={message.content} />
          {message.compatibility?.verdict && (
            <p className="rounded-md bg-steel-50 px-3 py-2 text-xs" aria-label="Compatibility verdict">
              <VerdictBadge verdict={message.compatibility.verdict} />
              {message.compatibility.explained_by_ai ? ' · explained by the AI helper, decided from the product listings' : ' · from the product listings'}
            </p>
          )}
          {message.estimate?.calculator_path && (
            <Link to={message.estimate.calculator_path} className="inline-block text-sm font-semibold text-amber-700 hover:underline">
              Work it out with real products in the quantity calculator
            </Link>
          )}
          {message.ai_mode === 'basic' && message.notice && (
            <p role="status" className="rounded-md bg-amber-100 px-3 py-2 text-xs">
              {message.notice}
            </p>
          )}
        </div>
        {message.products.length > 0 && (
          <ul aria-label="Recommended products" className="space-y-2">
            {message.products.map((product) => (
              <RecommendationCard key={product.id} product={product} />
            ))}
          </ul>
        )}
        {signedIn && addAll && addAll.type === 'add_all' && <AddAllButton label={addAll.label} variantIds={addAll.variant_ids} />}
        {message.questions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {message.questions.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onSuggest('')}
                className="rounded-full bg-steel-100 px-3 py-1.5 text-left text-xs font-medium text-ink-800 hover:bg-steel-200"
                title="Type your answer below"
              >
                <SparkIcon className="mr-1 inline size-3.5" />
                {question}
              </button>
            ))}
          </div>
        )}
      </div>
    </li>
  )
}

export function TypingIndicator() {
  return (
    <li className="flex justify-start" aria-live="polite">
      <div role="status" className="flex items-center gap-1.5 rounded-2xl rounded-bl-sm bg-white px-4 py-3 ring-1 ring-steel-200">
        <span className="sr-only">The assistant is thinking…</span>
        {[0, 150, 300].map((delay) => (
          <span key={delay} aria-hidden className="size-2 animate-bounce rounded-full bg-steel-400" style={{ animationDelay: `${delay}ms` }} />
        ))}
      </div>
    </li>
  )
}
