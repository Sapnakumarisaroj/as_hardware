import { useState } from 'react'
import { Link } from 'react-router'

import { EmptyState, ErrorState } from '@/components/feedback'
import { useProducts } from '@/features/catalog/api'
import { NAV_GROUPS } from '@/features/catalog/navGroups'
import { InfoPage } from '@/features/company/InfoPage'
import { formatPrice, pluralize } from '@/lib/format'

const DEPARTMENTS = NAV_GROUPS.flatMap((group) => group.departments)
const ROWS = 100 // the API's largest page

/** Today's prices for one department, straight from the catalogue (nothing typed in by hand). */
function DepartmentPrices({ slug, name }: { slug: string; name: string }) {
  const products = useProducts({ category: slug, ordering: 'price', page_size: String(ROWS) })
  if (products.isPending) return <p className="mt-4 text-sm text-ink-600">Loading prices…</p>
  if (products.isError) return <ErrorState error={products.error} onRetry={() => products.refetch()} title="Couldn’t load prices" />
  const rows = products.data.results
  if (!rows.length) return <EmptyState title={`No ${name} products listed yet`}>Call or email us for current prices.</EmptyState>
  const more = products.data.count - rows.length
  return (
    <div className="mt-4">
      <div className="overflow-x-auto rounded-xl ring-1 ring-steel-200">
        <table className="w-full min-w-[34rem] bg-white text-left text-sm">
          <caption className="sr-only">{name} prices</caption>
          <thead className="bg-steel-50 text-xs uppercase tracking-wide text-ink-600">
            <tr>
              <th scope="col" className="px-3 py-2.5 font-semibold">
                Product
              </th>
              <th scope="col" className="px-3 py-2.5 font-semibold">
                Unit
              </th>
              <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                Price
              </th>
              <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                MRP
              </th>
              <th scope="col" className="px-3 py-2.5 font-semibold">
                Bulk price
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-steel-100">
            {rows.map((product) => (
              <tr key={product.id}>
                <td className="px-3 py-2.5">
                  <Link to={`/p/${product.slug}`} className="font-medium text-ink-950 hover:text-amber-700 hover:underline">
                    {product.name}
                  </Link>
                  {product.variant_count > 1 && <span className="block text-xs text-ink-600">{product.variant_count} options · price from</span>}
                </td>
                <td className="px-3 py-2.5 text-ink-700">{product.unit}</td>
                <td className="px-3 py-2.5 text-right font-semibold text-ink-950">{formatPrice(product.price)}</td>
                <td className="px-3 py-2.5 text-right text-ink-600">{product.mrp && product.mrp !== product.price ? formatPrice(product.mrp) : '—'}</td>
                <td className="px-3 py-2.5 text-ink-700">
                  {product.bulk_pricing
                    ? `${formatPrice(product.bulk_pricing.lowest_unit_price)}${product.bulk_pricing.from_quantity ? ` from ${product.bulk_pricing.from_quantity}` : ''}`
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-600">
        Prices include GST and can change; the cart shows the price you pay.
        {more > 0 && (
          <>
            {' '}
            {pluralize(more, 'more product')} in{' '}
            <Link to={`/c/${slug}?ordering=price`} className="font-semibold text-ink-950 underline">
              {name}
            </Link>
            .
          </>
        )}
      </p>
    </div>
  )
}

/** /price-lists — live prices per department, bulk prices, and the quotation request for large orders. */
export function PriceListsPage() {
  const [slug, setSlug] = useState(DEPARTMENTS[0]?.[0] ?? '')
  const name = DEPARTMENTS.find(([s]) => s === slug)?.[1] ?? ''
  return (
    <InfoPage
      group="company"
      wide
      title="Price Lists"
      intro="Current prices for every department, taken live from our catalogue, plus how to get bulk prices and a quotation for larger orders."
    >
      <h2>Prices by department</h2>
      <p>Choose a department to see its products from the lowest price up.</p>
      <div role="group" aria-label="Department" className="mt-4 flex flex-wrap gap-2">
        {DEPARTMENTS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={slug === value}
            onClick={() => setSlug(value)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ring-1 transition-colors ${
              slug === value ? 'bg-ink-950 text-white ring-ink-950' : 'bg-white text-ink-800 ring-steel-200 hover:ring-amber-500'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <DepartmentPrices key={slug} slug={slug} name={name} />

      <h2>Bulk prices</h2>
      <p>
        Many products cost less per unit when you buy more. The product page shows each bulk price and the quantity it starts
        from, and the cart applies it automatically.
      </p>
      <p>
        <Link to="/products?bulk_pricing=true">See all products with bulk prices</Link>
      </p>

      <h2>Request a quotation</h2>
      <p>For project or trade quantities you can ask for a quotation before you order:</p>
      <ol>
        <li>Add the products and quantities you need to your cart.</li>
        <li>
          In the cart, choose <strong>Request a bulk quote</strong> and add a note if needed. Your cart stays as it is.
        </li>
        <li>
          We reply with quoted prices and a validity date. You can see the reply under <Link to="/account/quotes">My quotes</Link>,
          accept it and order at the quoted prices.
        </li>
      </ol>
      <div className="mt-5 flex flex-wrap gap-3">
        <Link to="/cart" className="btn-primary">
          Go to cart
        </Link>
        <Link to="/contact" className="btn-secondary">
          Contact us
        </Link>
      </div>
    </InfoPage>
  )
}
