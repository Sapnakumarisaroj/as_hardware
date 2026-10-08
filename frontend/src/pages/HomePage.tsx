import { Link } from 'react-router'

import { ErrorState } from '@/components/feedback'
import { BoltIcon, CameraIcon, ChevronRightIcon, ImageIcon, MicIcon, SparkIcon } from '@/components/icons'
import { useAuth } from '@/features/auth/context'
import { useCategories, useCollections, useProducts } from '@/features/catalog/api'
import { ProductRail, ProductStrip } from '@/features/catalog/components/ProductCollections'
import { useRecentlyViewed } from '@/features/catalog/recentlyViewed'
import { useNavGroups, type NavGroup } from '@/features/catalog/navGroups'
import type { Category, Collection, ProductSummary } from '@/features/catalog/types'
import { useServiceability } from '@/features/delivery/api'
import { isValidPincode, usePincode } from '@/features/delivery/location'
import { LiveOffersStrip } from '@/features/offers/components'
import { useWishlist } from '@/features/wishlist/api'
import { env } from '@/lib/env'
import { pluralize } from '@/lib/format'
import { HomeRecommendations } from '@/features/shopping/ProductRecommendations'
import { usePageMeta } from '@/lib/usePageMeta'

/*
 * The storefront home (Phase 16). Every section comes from the API and is left out when it has
 * nothing to show: departments and their rails are the shop's categories, curated lists are the shop's
 * collections (in the shop's order and with its names), delivery messages are the Phase 9 engine's for
 * the chosen PIN. No product, category or number is written into this page.
 */

/** 2. Headline + AI, photo and voice search (the search box itself is the header's, so there is only one). */
function SearchHero() {
  return (
    <section className="bg-ink-900 text-white">
      <div className="container-page py-8 md:py-12">
        <h1 className="max-w-3xl text-2xl font-extrabold leading-tight sm:text-4xl">
          Making furniture, fitting a kitchen or fixing a door? Find the right hardware and get it delivered.
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-steel-200 sm:text-base">
          Search by name, size, grade or job. Prices, stock and delivery times come straight from our stores.
        </p>
        <ul className="mt-5 flex flex-wrap gap-2 text-sm" aria-label="Other ways to find products">
          <li>
            <Link
              to="/ai-assistant"
              className="inline-flex items-center gap-1.5 rounded-full bg-ink-800 px-3 py-1.5 ring-1 ring-ink-600 hover:text-amber-500"
            >
              <SparkIcon className="size-4 text-amber-500" />
              Ask the AI assistant
            </Link>
          </li>
          <li>
            <Link
              to="/image-search"
              className="inline-flex items-center gap-1.5 rounded-full bg-ink-800 px-3 py-1.5 ring-1 ring-ink-600 hover:text-amber-500"
            >
              <CameraIcon className="size-4 text-amber-500" />
              Search with a photo
            </Link>
          </li>
          <li>
            <Link
              to="/voice"
              className="inline-flex items-center gap-1.5 rounded-full bg-ink-800 px-3 py-1.5 ring-1 ring-ink-600 hover:text-amber-500"
            >
              <MicIcon className="size-4 text-amber-500" />
              Shop by voice
            </Link>
          </li>
          <li>
            <Link
              to="/brands"
              className="inline-flex items-center gap-1.5 rounded-full bg-ink-800 px-3 py-1.5 ring-1 ring-ink-600 hover:text-amber-500"
            >
              Shop by brand
            </Link>
          </li>
        </ul>
      </div>
    </section>
  )
}

function departmentsWithProducts(categories: Category[] | undefined): Category[] {
  return (categories ?? []).filter((c) => (c.product_count ?? 0) > 0)
}

/** A card's pictures: up to three real product photos of the group's own categories. */
function GroupCollage({ group }: { group: NavGroup }) {
  const [first, ...rest] = group.images
  const img = 'size-full object-cover transition-transform duration-200 group-hover:scale-[1.03]'
  if (!first) {
    return (
      <span aria-hidden className="grid size-full place-items-center text-steel-400">
        <ImageIcon className="size-10" />
      </span>
    )
  }
  if (rest.length < 2) return <img src={first} alt={`${group.name}: example product`} loading="lazy" className={img} />
  return (
    <span className="grid size-full grid-cols-3 grid-rows-2 gap-0.5">
      <span className="col-span-2 row-span-2 overflow-hidden">
        <img src={first} alt={`${group.name}: example product`} loading="lazy" className={img} />
      </span>
      {rest.slice(0, 2).map((src) => (
        <span key={src} className="overflow-hidden">
          <img src={src} alt="" loading="lazy" className={img} />
        </span>
      ))}
    </span>
  )
}

/** 3. Shop by category — the four groups of the shop's ten departments (same as the header). */
function ShopByGroup() {
  const { groups, categories } = useNavGroups()
  if (categories.isError) {
    return <ErrorState error={categories.error} onRetry={() => categories.refetch()} title="Couldn’t load categories" />
  }
  if (categories.isPending) {
    return (
      <ul aria-label="Loading categories" className="grid grid-cols-1 gap-4 py-6 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <li key={i} className="h-72 animate-pulse rounded-xl bg-white ring-1 ring-steel-200" />
        ))}
      </ul>
    )
  }
  if (!groups.length) return null
  return (
    <section id="categories" aria-labelledby="departments-heading" className="scroll-mt-32 py-6">
      <h2 id="departments-heading" className="mb-4 text-xl font-bold text-ink-950">
        Shop by category
      </h2>
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {groups.map((group) => (
          <li key={group.slug} className="flex">
            <article className="group flex w-full flex-col overflow-hidden rounded-xl bg-white ring-1 ring-steel-200 transition-shadow hover:shadow-md hover:ring-amber-500">
              <Link to={group.href} tabIndex={-1} aria-hidden className="block aspect-[4/3] w-full overflow-hidden bg-steel-100">
                <GroupCollage group={group} />
              </Link>
              <div className="flex flex-1 flex-col px-4 py-3">
                <h3 className="text-lg font-extrabold leading-tight text-ink-950 lg:text-[15px] xl:text-lg">
                  <Link to={group.href} className="hover:text-amber-600">
                    {group.name}
                  </Link>
                </h3>
                {group.productCount !== null && <p className="mt-0.5 text-xs text-ink-600">{pluralize(group.productCount, 'product')}</p>}
                <ul className="mt-2 flex flex-wrap gap-1.5" aria-label={`${group.name} categories`}>
                  {group.entries.map((entry) => (
                    <li key={entry.slug}>
                      <Link to={entry.href} className="inline-block whitespace-nowrap rounded-full bg-steel-50 px-2.5 py-1 text-xs text-ink-800 ring-1 ring-steel-200 hover:text-amber-600 hover:ring-amber-500">
                        {entry.name}
                      </Link>
                    </li>
                  ))}
                </ul>
                <Link to={group.href} className="mt-auto flex items-center gap-0.5 pt-3 text-sm font-semibold text-amber-600 hover:underline">
                  Shop {group.name}
                  <ChevronRightIcon className="size-4" />
                </Link>
              </div>
            </article>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** 4. Fast delivery — only for a PIN the engine can deliver fast to right now. */
function FastDeliveryRail() {
  const pincode = usePincode()
  const check = useServiceability(pincode)
  const fast = isValidPincode(pincode) && check.data?.fast_delivery_available
  return (
    <ProductRail
      title="Fast delivery to you"
      subtitle={fast ? `${check.data?.label} to ${pincode} · from stores near you` : undefined}
      icon={<BoltIcon className="size-5 text-amber-500" />}
      params={{ fast_delivery: 'true', ordering: 'popular' }}
      viewAllHref="/products?fast_delivery=true"
      enabled={Boolean(fast)}
    />
  )
}

const RULE_LINKS: Partial<Record<Collection['rule'], string>> = {
  best_sellers: '/products?ordering=popular',
  new_launches: '/products?ordering=newest',
  bulk_pricing: '/products?bulk_pricing=true',
}

/** 5–8. The shop's curated lists (deals of the week, best sellers, new launches, essentials…), in its order. */
function CollectionSections({ collections }: { collections: Collection[] }) {
  return (
    <>
      {collections
        .filter((collection) => collection.rule !== 'bulk_pricing')
        .map((collection) => (
        <ProductStrip
          key={collection.id}
          title={collection.name}
          subtitle={collection.description || undefined}
          products={collection.products}
          viewAllHref={RULE_LINKS[collection.rule]}
        />
        ))}
    </>
  )
}

/** Lists the shop hasn't curated still appear from live data (sold units, newest, bulk prices). */
function FallbackRails({ collections }: { collections: Collection[] }) {
  const rules = new Set(collections.map((c) => c.rule))
  return (
    <>
      {!rules.has('best_sellers') && (
        <ProductRail title="Best sellers" params={{ bestseller: 'true', ordering: 'popular' }} viewAllHref="/products?ordering=popular" />
      )}
      {!rules.has('new_launches') && (
        <ProductRail title="New arrivals" params={{ ordering: 'newest' }} viewAllHref="/products?ordering=newest" />
      )}
    </>
  )
}

/** 9–12. One rail per department, named and ordered as in the catalogue. */
function DepartmentRails() {
  const categories = useCategories()
  return (
    <>
      {departmentsWithProducts(categories.data).map((department) => (
        <ProductRail
          key={department.id}
          title={department.name}
          params={{ category: department.slug, ordering: 'popular', in_stock: 'true' }}
          viewAllHref={`/c/${department.slug}`}
        />
      ))}
    </>
  )
}

/** 13. Bulk buying — the shop's bulk list if it has one, else every product with bulk prices. */
function BulkBuyingRail({ collections }: { collections: Collection[] }) {
  const own = collections.filter((c) => c.rule === 'bulk_pricing')
  if (own.length) {
    return (
      <>
        {own.map((collection) => (
          <ProductStrip
            key={collection.id}
            title={collection.name}
            subtitle={collection.description || undefined}
            products={collection.products}
            viewAllHref={RULE_LINKS.bulk_pricing}
          />
        ))}
      </>
    )
  }
  return (
    <ProductRail
      title="Bulk buying"
      subtitle="Lower prices per unit when you buy more"
      params={{ bulk_pricing: 'true' }}
      viewAllHref="/products?bulk_pricing=true"
    />
  )
}

/** 15–16. The AI entry points. */
function AiEntryPoints() {
  const cards = [
    {
      to: '/ai-assistant',
      title: 'AI hardware assistant',
      text: 'Describe the job in English, Hindi or Hinglish and get products from our catalogue.',
      icon: <SparkIcon className="size-6 text-amber-500" />,
    },
    {
      to: '/projects',
      title: 'Plan a project',
      text: 'Describe the job and get a kit of materials from our catalogue, priced and checked for delivery.',
      icon: <ChevronRightIcon className="size-6 text-amber-500" />,
    },
    {
      to: '/quantity',
      title: 'How much do I need?',
      text: 'Screws, wall plugs and more: describe the job and get the quantity with real products and prices.',
      icon: <SparkIcon className="size-6 text-amber-500" />,
    },
    {
      to: '/budget',
      title: 'Shop within a budget',
      text: 'Tell us the job and your budget; we build a cart from real products that stays within it.',
      icon: <SparkIcon className="size-6 text-amber-500" />,
    },
    {
      to: '/image-search',
      title: 'Search with a photo',
      text: 'Take a photo of a part and find it in our catalogue.',
      icon: <CameraIcon className="size-6 text-amber-500" />,
    },
    {
      to: '/voice',
      title: 'Shop by voice',
      text: 'Say “5 sheets of 18 mm plywood” in English, Hindi or Hinglish and see the price for that quantity.',
      icon: <MicIcon className="size-6 text-amber-500" />,
    },
  ]
  return (
    <section aria-labelledby="ai-heading" className="py-6">
      <h2 id="ai-heading" className="mb-4 text-xl font-bold text-ink-950">
        Not sure what you need?
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <li key={card.title} className="flex">
            <Link
              to={card.to}
              className="flex w-full items-start gap-3 rounded-lg bg-ink-900 p-4 text-white ring-1 ring-ink-700 hover:ring-amber-500 focus-visible:ring-amber-500"
            >
              {card.icon}
              <span>
                <span className="block font-bold">{card.title}</span>
                <span className="mt-1 block text-sm text-steel-200">{card.text}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** 17. Recently viewed — slugs from this browser, products always loaded fresh. */
function useRecentProducts() {
  const slugs = useRecentlyViewed()
  const query = useProducts({ slugs: slugs.join(','), page_size: String(slugs.length || 1) }, { enabled: slugs.length > 0 })
  const bySlug = new Map((query.data?.results ?? []).map((p) => [p.slug, p]))
  return slugs.map((slug) => bySlug.get(slug)).filter((p): p is ProductSummary => Boolean(p))
}

/** 18. Recommended — more from the category of a saved item, or of the last product viewed. */
function RecommendedForYou({ recent }: { recent: ProductSummary[] }) {
  const { status } = useAuth()
  const wishlist = useWishlist()
  const saved = status === 'authenticated' ? wishlist.data?.[0]?.product : undefined
  const fromSaved = saved?.subcategory ?? saved?.category
  const lastViewed = recent[0]
  const fromViewed = lastViewed?.subcategory ?? lastViewed?.category
  const basis = fromSaved ?? fromViewed
  const exclude = [...(wishlist.data?.map((item) => item.product.slug) ?? []), ...recent.map((p) => p.slug)].join(',')
  return (
    <ProductRail
      title="Recommended for you"
      subtitle={basis ? `Because you ${fromSaved ? 'saved' : 'looked at'} items in ${basis.name}` : undefined}
      params={{ category: basis?.slug ?? '', exclude, in_stock: 'true' }}
      enabled={Boolean(basis)}
    />
  )
}

export function HomePage() {
  usePageMeta(null, `${env.appName}: plywood, Fevicol, hinges, kitchen and wardrobe fittings, door locks, tools and safety gear with live prices, stock and delivery times.`)
  const collections = useCollections()
  const lists = collections.data ?? []
  const recent = useRecentProducts()
  return (
    <>
      <SearchHero />
      <div className="container-page">
        <ShopByGroup />
        <FastDeliveryRail />
        {collections.isSuccess && <CollectionSections collections={lists} />}
        {!collections.isPending && <FallbackRails collections={lists} />}
        <DepartmentRails />
        {!collections.isPending && <BulkBuyingRail collections={lists} />}
        <LiveOffersStrip />
        <AiEntryPoints />
        <HomeRecommendations />
        <ProductStrip title="Recently viewed" products={recent} />
        <RecommendedForYou recent={recent} />
      </div>
    </>
  )
}
