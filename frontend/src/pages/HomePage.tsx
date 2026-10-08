import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { ErrorState } from '@/components/feedback'
import { HeroArt } from '@/components/HeroArt'
import {
  BoltIcon,
  CalculatorIcon,
  CameraIcon,
  CashIcon,
  ChevronRightIcon,
  ClipboardIcon,
  ImageIcon,
  LayersIcon,
  MicIcon,
  PinIcon,
  PuzzleIcon,
  ReceiptIcon,
  ReturnIcon,
  SparkIcon,
  TruckIcon,
} from '@/components/icons'
import { useAuth } from '@/features/auth/context'
import { useCollections, useProducts } from '@/features/catalog/api'
import { ProductRail, ProductStrip } from '@/features/catalog/components/ProductCollections'
import { useNavGroups, type NavGroup } from '@/features/catalog/navGroups'
import { useRecentlyViewed } from '@/features/catalog/recentlyViewed'
import type { Collection, ProductSummary } from '@/features/catalog/types'
import { useServiceability } from '@/features/delivery/api'
import { isValidPincode, usePincode } from '@/features/delivery/location'
import { LiveOffersStrip } from '@/features/offers/components'
import { HomeRecommendations } from '@/features/shopping/ProductRecommendations'
import { useWishlist } from '@/features/wishlist/api'
import { env } from '@/lib/env'
import { pluralize } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

/*
 * The storefront home. Every product section comes from the API and is left out when it has nothing
 * to show: categories are the shop's four groups over its real departments, curated lists are the
 * shop's collections, delivery wording follows the Phase 9 engine for the chosen PIN. No product,
 * price or delivery time is written into this page.
 */

/** 1. Hero: headline, the two main actions and an honest delivery line. */
function Hero() {
  const pincode = usePincode()
  const check = useServiceability(pincode)
  const fastHere = isValidPincode(pincode) && check.data?.serviceable && check.data.fast_delivery_available
  return (
    <section className="relative overflow-hidden bg-ink-950 text-white">
      <div aria-hidden className="pointer-events-none absolute -right-40 -top-40 size-[34rem] rounded-full bg-amber-500/20 blur-3xl" />
      <div aria-hidden className="pointer-events-none absolute -bottom-48 -left-24 size-[26rem] rounded-full bg-amber-500/10 blur-3xl" />
      <div className="container-page relative grid items-center gap-8 py-10 sm:py-14 lg:grid-cols-[1.05fr_1fr] lg:gap-12 lg:py-16">
        <div className="animate-rise">
          <p className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold text-amber-400 ring-1 ring-white/15">
            <PinIcon className="size-3.5" />
            Delivering across Bengaluru
          </p>
          <h1 className="mt-4 text-4xl font-extrabold leading-[1.08] sm:text-5xl lg:text-6xl">
            Hardware for <span className="text-amber-400">every project</span>
          </h1>
          <p className="mt-4 max-w-xl text-base text-steel-200 sm:text-lg">
            Quality hardware, tools and fittings delivered across Bengaluru. Live prices, real stock and delivery times for your
            address.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link to="/products" className="btn-primary px-6 py-3 text-base">
              Shop now
              <ChevronRightIcon className="size-4" />
            </Link>
            <a href="#categories" className="btn-secondary bg-white/10 px-6 py-3 text-base text-white ring-white/25 hover:bg-white/15">
              Browse categories
            </a>
          </div>
          <ul className="mt-7 flex flex-wrap gap-x-6 gap-y-2 text-sm text-steel-200" aria-label="Delivery">
            <li className="inline-flex items-center gap-2">
              <BoltIcon className="size-4 text-amber-400" />
              {fastHere ? `Fast delivery to ${pincode}: ${check.data?.label}` : 'Fast delivery where eligible'}
            </li>
            <li className="inline-flex items-center gap-2">
              <TruckIcon className="size-4 text-amber-400" />
              Standard delivery across Bengaluru
            </li>
          </ul>
        </div>
        <div className="animate-rise [animation-delay:120ms]">
          <HeroArt className="mx-auto w-full max-w-[18rem] drop-shadow-2xl sm:max-w-md lg:max-w-xl" />
        </div>
      </div>
    </section>
  )
}

/** 2. What the platform actually offers (only claims the system backs). */
const TRUST: [string, string, ReactNode][] = [
  ['Cash on delivery', 'On eligible orders', <CashIcon key="c" />],
  ['Fast Bengaluru delivery', 'Where your address allows', <BoltIcon key="b" />],
  ['Easy returns', 'Request from your orders', <ReturnIcon key="r" />],
  ['Bulk pricing', 'Lower prices for bigger orders', <LayersIcon key="l" />],
  ['GST-inclusive prices', 'No surprises at checkout', <ReceiptIcon key="g" />],
]

function TrustStrip() {
  return (
    <section aria-label="Why shop with us" className="relative z-10 -mt-6 sm:-mt-8">
      <ul className="card grid grid-cols-2 divide-steel-100 p-2 sm:grid-cols-3 lg:grid-cols-5 lg:divide-x">
        {TRUST.map(([title, text, icon], i) => (
          <li key={title} className={`flex items-center gap-2.5 rounded-xl p-2.5 sm:gap-3 sm:p-3 ${i === TRUST.length - 1 ? 'col-span-2 sm:col-span-1' : ''}`}>
            <span className="grid size-9 shrink-0 sm:size-10 place-items-center rounded-xl bg-amber-50 text-amber-700 ring-1 ring-amber-100 [&>svg]:size-5">
              {icon}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-ink-950">{title}</span>
              <span className="hidden text-xs text-ink-600 sm:block">{text}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** A card's pictures: up to three real product photos of the group's own categories. */
function GroupCollage({ group }: { group: NavGroup }) {
  const [first, ...rest] = group.images
  const img = 'size-full object-cover transition-transform duration-500 ease-out group-hover:scale-105'
  if (!first) {
    return (
      <span aria-hidden className="grid size-full place-items-center text-steel-400">
        <ImageIcon className="size-10" />
      </span>
    )
  }
  if (rest.length < 2) return <img src={first} alt={`${group.name}: example product`} loading="lazy" className={img} />
  return (
    <span className="grid size-full grid-cols-3 grid-rows-2 gap-1">
      <span className="col-span-2 row-span-2 overflow-hidden rounded-l-xl">
        <img src={first} alt={`${group.name}: example product`} loading="lazy" className={img} />
      </span>
      {rest.slice(0, 2).map((src, i) => (
        <span key={src} className={`overflow-hidden ${i === 0 ? 'rounded-tr-xl' : 'rounded-br-xl'}`}>
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
      <ul aria-label="Loading categories" className="grid grid-cols-1 gap-4 py-8 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <li key={i} className="card h-80 animate-pulse" />
        ))}
      </ul>
    )
  }
  if (!groups.length) return null
  return (
    <section id="categories" aria-labelledby="departments-heading" className="scroll-mt-32 py-10 sm:py-12">
      <div className="mb-5 flex items-end justify-between gap-4 sm:mb-6">
        <div>
          <p className="eyebrow">Browse the range</p>
          <h2 id="departments-heading" className="section-title">
            Shop by category
          </h2>
        </div>
        <Link to="/products" className="hidden text-sm font-semibold text-amber-700 hover:underline sm:inline">
          All products
        </Link>
      </div>
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 lg:gap-5">
        {groups.map((group, index) => (
          <li key={group.slug} className="flex animate-rise" style={{ animationDelay: `${index * 70}ms` }}>
            <article className="card card-hover group flex w-full flex-col overflow-hidden">
              <Link to={group.href} tabIndex={-1} aria-hidden className="m-2 mb-0 block aspect-[4/3] overflow-hidden rounded-xl bg-steel-100">
                <GroupCollage group={group} />
              </Link>
              <div className="flex flex-1 flex-col p-4 sm:p-5">
                <h3 className="text-lg font-bold leading-tight text-ink-950 lg:text-[17px] xl:text-lg">
                  <Link to={group.href} className="hover:text-amber-700">
                    {group.name}
                  </Link>
                </h3>
                <p className="mt-1 text-sm text-ink-600">{group.blurb}</p>
                <ul className="mt-3 flex flex-wrap gap-1.5" aria-label={`${group.name} categories`}>
                  {group.entries.map((entry) => (
                    <li key={entry.slug}>
                      <Link
                        to={entry.href}
                        className="inline-block whitespace-nowrap rounded-full bg-steel-50 px-2.5 py-1 text-xs text-ink-800 ring-1 ring-steel-200 transition hover:bg-amber-50 hover:text-amber-700 hover:ring-amber-200"
                      >
                        {entry.name}
                      </Link>
                    </li>
                  ))}
                </ul>
                <div className="mt-auto flex items-center justify-between gap-3 pt-4">
                  {group.productCount !== null && <span className="text-xs text-ink-600">{pluralize(group.productCount, 'product')}</span>}
                  <Link to={group.href} className="btn-dark ml-auto px-3.5 py-2 text-sm group-hover:bg-amber-500 group-hover:text-ink-950">
                    Shop now
                    <span className="sr-only"> {group.name}</span>
                    <ChevronRightIcon className="size-4" />
                  </Link>
                </div>
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
      eyebrow="Arriving soon"
      subtitle={fast ? `${check.data?.label} to ${pincode} · from stores near you` : undefined}
      icon={<BoltIcon className="size-5 text-amber-400" />}
      params={{ fast_delivery: 'true', ordering: 'popular' }}
      viewAllHref="/products?fast_delivery=true"
      enabled={Boolean(fast)}
      tone="dark"
    />
  )
}

const RULE_LINKS: Partial<Record<Collection['rule'], string>> = {
  best_sellers: '/products?ordering=popular',
  new_launches: '/products?ordering=newest',
  bulk_pricing: '/products?bulk_pricing=true',
}

/** 5. The shop's curated lists (deals of the week, best sellers, new launches, essentials…), in its order. */
function CollectionSections({ collections }: { collections: Collection[] }) {
  return (
    <>
      {collections
        .filter((collection) => collection.rule !== 'bulk_pricing')
        .map((collection) => (
          <ProductStrip
            key={collection.id}
            title={collection.name}
            eyebrow="Curated"
            subtitle={collection.description || undefined}
            products={collection.products}
            viewAllHref={RULE_LINKS[collection.rule]}
          />
        ))}
    </>
  )
}

/** Lists the shop hasn't curated still appear from live data (sold units, newest). */
function FallbackRails({ collections }: { collections: Collection[] }) {
  const rules = new Set(collections.map((c) => c.rule))
  return (
    <>
      {!rules.has('best_sellers') && (
        <ProductRail
          title="Best sellers"
          eyebrow="Most bought"
          params={{ bestseller: 'true', ordering: 'popular' }}
          viewAllHref="/products?ordering=popular"
        />
      )}
      {!rules.has('new_launches') && (
        <ProductRail title="New arrivals" eyebrow="Just in" params={{ ordering: 'newest' }} viewAllHref="/products?ordering=newest" />
      )}
    </>
  )
}

/** 6. Popular hardware — a grid, so the page doesn't become one long row of rows. */
function PopularHardware() {
  return (
    <ProductRail
      title="Popular hardware"
      eyebrow="Customers’ picks"
      params={{ ordering: 'popular', in_stock: 'true' }}
      viewAllHref="/products?ordering=popular"
      layout="grid"
    />
  )
}

/** 7. Delivery promise, worded the way the engine works: fast where eligible, standard everywhere else. */
function DeliveryBanner() {
  const points: [ReactNode, string, string][] = [
    [<PinIcon key="p" />, 'Bengaluru', 'Every Bengaluru PIN code'],
    [<BoltIcon key="b" />, 'Fast delivery where eligible', 'Worked out for your address, stock and riders'],
    [<TruckIcon key="t" />, 'Standard delivery across Bengaluru', 'A delivery window when fast isn’t possible'],
  ]
  return (
    <section aria-labelledby="delivery-heading" className="my-8 animate-rise overflow-hidden rounded-3xl bg-ink-900 text-white">
      <div className="relative grid gap-6 p-6 sm:p-8 lg:grid-cols-[1fr_1.4fr] lg:items-center lg:p-10">
        <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 size-80 rounded-full bg-amber-500/15 blur-3xl" />
        <div className="relative">
          <p className="eyebrow text-amber-400">Delivery</p>
          <h2 id="delivery-heading" className="mt-1 text-2xl font-bold sm:text-3xl">
            Fast hardware delivery across Bengaluru
          </h2>
          <p className="mt-2 text-sm text-steel-200">
            Choose your PIN code in the header to see the delivery time for your address. The time for your order is confirmed in the
            cart.
          </p>
        </div>
        <ul className="relative grid gap-3 sm:grid-cols-3">
          {points.map(([icon, title, text]) => (
            <li key={title} className="rounded-2xl bg-white/5 p-4 ring-1 ring-white/10">
              <span className="grid size-9 place-items-center rounded-lg bg-amber-500 text-ink-950 [&>svg]:size-5">{icon}</span>
              <p className="mt-3 text-sm font-semibold">{title}</p>
              <p className="mt-0.5 text-xs text-steel-200">{text}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

/** 8. Bulk buying — the shop's bulk list if it has one, else every product with bulk prices. */
function BulkBuyingRail({ collections }: { collections: Collection[] }) {
  const own = collections.filter((c) => c.rule === 'bulk_pricing')
  if (own.length) {
    return (
      <>
        {own.map((collection) => (
          <ProductStrip
            key={collection.id}
            title={collection.name}
            eyebrow="Buy more, pay less"
            subtitle={collection.description || undefined}
            products={collection.products}
            viewAllHref={RULE_LINKS.bulk_pricing}
            tone="tinted"
          />
        ))}
      </>
    )
  }
  return (
    <ProductRail
      title="Bulk buying"
      eyebrow="Buy more, pay less"
      subtitle="Lower prices per unit when you buy more"
      params={{ bulk_pricing: 'true' }}
      viewAllHref="/products?bulk_pricing=true"
      tone="tinted"
    />
  )
}

/** 9. The AI tools, kept out of the navigation. */
const AI_TOOLS: [string, string, string, ReactNode][] = [
  ['AI assistant', 'Describe the job, get the right parts', '/ai-assistant', <SparkIcon key="a" />],
  ['Image search', 'Snap a part to find it', '/image-search', <CameraIcon key="i" />],
  ['Voice search', 'Say what you need in any language mix', '/voice', <MicIcon key="v" />],
  ['Project builder', 'A priced kit for your job', '/projects', <ClipboardIcon key="p" />],
  ['Quantity AI', 'How many screws, plugs and more', '/quantity', <CalculatorIcon key="q" />],
  ['Compatibility checker', 'Will these parts work together?', '/ai-assistant', <PuzzleIcon key="c" />],
]

function AiSection() {
  return (
    <section aria-labelledby="ai-heading" className="py-10 sm:py-12">
      <div className="mb-5 sm:mb-6">
        <p className="eyebrow">Shopping tools</p>
        <h2 id="ai-heading" className="section-title">
          Smarter way to buy hardware
        </h2>
      </div>
      <ul className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 xl:grid-cols-6">
        {AI_TOOLS.map(([title, text, to, icon], index) => (
          <li key={title} className="flex animate-rise" style={{ animationDelay: `${index * 50}ms` }}>
            <Link to={to} className="card card-hover group flex w-full flex-col p-4 sm:p-5">
              <span className="grid size-11 place-items-center rounded-xl bg-ink-900 text-amber-400 transition group-hover:bg-amber-500 group-hover:text-ink-950 [&>svg]:size-5">
                {icon}
              </span>
              <span className="mt-4 text-sm font-semibold text-ink-950">{title}</span>
              <span className="mt-1 text-xs leading-relaxed text-ink-600">{text}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** 10. Recently viewed — slugs from this browser, products always loaded fresh. */
function useRecentProducts() {
  const slugs = useRecentlyViewed()
  const query = useProducts({ slugs: slugs.join(','), page_size: String(slugs.length || 1) }, { enabled: slugs.length > 0 })
  const bySlug = new Map((query.data?.results ?? []).map((p) => [p.slug, p]))
  return slugs.map((slug) => bySlug.get(slug)).filter((p): p is ProductSummary => Boolean(p))
}

/** 11. Recommended — more from the category of a saved item, or of the last product viewed. */
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
      eyebrow="For you"
      subtitle={basis ? `Because you ${fromSaved ? 'saved' : 'looked at'} items in ${basis.name}` : undefined}
      params={{ category: basis?.slug ?? '', exclude, in_stock: 'true' }}
      enabled={Boolean(basis)}
    />
  )
}

export function HomePage() {
  usePageMeta(null, `${env.appName}: plywood, Fevicol, hinges, kitchen and wardrobe fittings, door locks, tools and safety gear delivered across Bengaluru.`)
  const collections = useCollections()
  const lists = collections.data ?? []
  const recent = useRecentProducts()
  return (
    <>
      <Hero />
      <div className="container-page">
        <TrustStrip />
        <ShopByGroup />
        <FastDeliveryRail />
        {collections.isSuccess && <CollectionSections collections={lists} />}
        {!collections.isPending && <FallbackRails collections={lists} />}
        <PopularHardware />
        <DeliveryBanner />
        {!collections.isPending && <BulkBuyingRail collections={lists} />}
        <LiveOffersStrip />
        <AiSection />
        <HomeRecommendations />
        <ProductStrip title="Recently viewed" eyebrow="Pick up where you left off" products={recent} />
        <RecommendedForYou recent={recent} />
      </div>
    </>
  )
}
