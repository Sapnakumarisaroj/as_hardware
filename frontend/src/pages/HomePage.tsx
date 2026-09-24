import { Link } from 'react-router'

import { ErrorState } from '@/components/feedback'
import { BoltIcon, ChevronRightIcon, SearchIcon } from '@/components/icons'
import { useAuth } from '@/features/auth/context'
import { useCategories } from '@/features/catalog/api'
import { ProductRail } from '@/features/catalog/components/ProductCollections'
import type { Category } from '@/features/catalog/types'
import { useWishlist } from '@/features/wishlist/api'
import { env } from '@/lib/env'
import { pluralize } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const CATEGORY_ACCENTS = ['bg-amber-100', 'bg-steel-100', 'bg-white', 'bg-amber-100', 'bg-steel-100', 'bg-white']

function Hero() {
  return (
    <section className="bg-ink-900 text-white">
      <div className="container-page grid items-center gap-8 py-10 md:grid-cols-[1.3fr_1fr] md:py-14">
        <div>
          <p className="text-sm font-semibold uppercase tracking-widest text-amber-500">
            Electrical · Plumbing · Tools · Construction · Safety
          </p>
          <h1 className="mt-3 text-3xl font-extrabold leading-tight sm:text-5xl">
            The right part for the job, from stores near you.
          </h1>
          <p className="mt-4 max-w-xl text-base text-steel-200 sm:text-lg">
            Browse by category or search by size, brand or specification. Every price and stock status comes
            straight from our stores.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link to="/products" className="btn-primary px-5 py-3 text-base">
              Shop all products
            </Link>
            <a href="#categories" className="btn-secondary px-5 py-3 text-base">
              Browse categories
            </a>
          </div>
        </div>
        <div className="rounded-xl bg-ink-800 p-5 ring-1 ring-ink-600">
          <p className="flex items-center gap-2 font-semibold">
            <SearchIcon className="size-5 text-amber-500" />
            Try searching for
          </p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {['impact drill', '1.5 sq mm wire', 'PVC pipe', 'water tap', 'safety gloves', 'MCB'].map((term) => (
              <li key={term}>
                <Link
                  to={`/search?q=${encodeURIComponent(term)}`}
                  className="inline-block rounded-full bg-ink-900 px-3 py-1.5 text-sm text-steel-200 ring-1 ring-ink-600 hover:text-amber-500"
                >
                  {term}
                </Link>
              </li>
            ))}
          </ul>
          <p className="mt-4 flex items-start gap-2 text-sm text-steel-200">
            <BoltIcon className="mt-0.5 size-4 shrink-0 text-amber-500" />
            Items stocked at a store with fast delivery are marked. Delivery time is confirmed for your address at
            checkout.
          </p>
        </div>
      </div>
    </section>
  )
}

function CategoryTile({ category, index }: { category: Category; index: number }) {
  return (
    <li className={`rounded-lg p-4 ring-1 ring-steel-200 ${CATEGORY_ACCENTS[index % CATEGORY_ACCENTS.length]}`}>
      <Link to={`/c/${category.slug}`} className="group flex items-center justify-between">
        <span>
          <span className="block text-base font-bold text-ink-950 group-hover:text-amber-600">{category.name}</span>
          {category.product_count !== null && (
            <span className="text-xs text-ink-600">{pluralize(category.product_count, 'product')}</span>
          )}
        </span>
        <ChevronRightIcon className="size-5 text-ink-600" />
      </Link>
      {category.children.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {category.children.slice(0, 5).map((child) => (
            <li key={child.id}>
              <Link
                to={`/c/${child.slug}`}
                className="inline-block rounded-full bg-white px-2.5 py-1 text-xs text-ink-800 ring-1 ring-steel-200 hover:text-amber-600"
              >
                {child.name}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function PopularCategories() {
  const categories = useCategories()
  return (
    <section id="categories" aria-labelledby="categories-heading" className="scroll-mt-32 py-6">
      <h2 id="categories-heading" className="mb-4 text-xl font-bold text-ink-950">
        Shop by category
      </h2>
      {categories.isPending ? (
        <ul aria-label="Loading categories" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="h-28 animate-pulse rounded-lg bg-white ring-1 ring-steel-200" />
          ))}
        </ul>
      ) : categories.isError ? (
        <ErrorState error={categories.error} onRetry={() => categories.refetch()} title="Couldn’t load categories" />
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[...categories.data]
            .sort((a, b) => (b.product_count ?? 0) - (a.product_count ?? 0))
            .map((category, index) => (
              <CategoryTile key={category.id} category={category} index={index} />
            ))}
        </ul>
      )}
    </section>
  )
}

/** "Based on your wishlist": more from the subcategory of the latest saved item. */
function RecommendedForYou() {
  const { status } = useAuth()
  const wishlist = useWishlist()
  const latest = wishlist.data?.[0]?.product
  const basis = latest?.subcategory ?? latest?.category
  const exclude = wishlist.data?.map((item) => item.product.slug).join(',') ?? ''
  return (
    <ProductRail
      title="Recommended for you"
      subtitle={basis ? `Because you saved items in ${basis.name}` : undefined}
      params={{ category: basis?.slug ?? '', exclude, in_stock: 'true' }}
      enabled={status === 'authenticated' && Boolean(basis)}
    />
  )
}

export function HomePage() {
  usePageMeta(null, `${env.appName}: hardware, tools, electrical and plumbing supplies with live prices and stock.`)
  return (
    <>
      <Hero />
      <div className="container-page">
        <PopularCategories />
        <RecommendedForYou />
        <ProductRail
          title="Today’s offers"
          subtitle="Biggest discounts on MRP right now"
          params={{ discount: '10', ordering: 'discount', in_stock: 'true' }}
          viewAllHref="/products?discount=10&ordering=discount"
        />
        <ProductRail
          title="Best sellers"
          params={{ bestseller: 'true', ordering: 'popular' }}
          viewAllHref="/products?ordering=popular"
        />
        <ProductRail title="Featured products" params={{ featured: 'true' }} viewAllHref="/products" />
        <ProductRail
          title="Fast delivery"
          subtitle="Stocked at stores with fast delivery — timing confirmed for your address at checkout"
          icon={<BoltIcon className="size-5 text-amber-500" />}
          params={{ fast_delivery: 'true', ordering: 'popular' }}
          viewAllHref="/products?fast_delivery=true"
        />
        <ProductRail
          title="Recently added"
          params={{ ordering: 'newest' }}
          viewAllHref="/products?ordering=newest"
        />
      </div>
    </>
  )
}
