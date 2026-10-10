import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { HeroArt } from '@/components/HeroArt'
import {
  BoltIcon,
  CalculatorIcon,
  CameraIcon,
  ChevronRightIcon,
  ClipboardIcon,
  CompareIcon,
  ImageIcon,
  LayersIcon,
  MicIcon,
  PinIcon,
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
import { useDeliveryPromise, useServiceability } from '@/features/delivery/api'
import { isValidPincode, usePincode } from '@/features/delivery/location'
import { LiveOffersStrip } from '@/features/offers/components'
import { useHomeRecommendations } from '@/features/shopping/api'
import { RecommendationRails } from '@/features/shopping/components'
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

/**
 * What may be said about fast delivery right now. `minutes` is the shop's configured limit (GET
 * /delivery/promise/) and is null when that can't be loaded: then nothing about fast delivery is
 * claimed. With a PIN, the delivery engine's answer for it: fast here, standard only, or not served.
 */
function useDeliveryClaims() {
  const promise = useDeliveryPromise()
  const pincode = usePincode()
  const check = useServiceability(pincode)
  const minutes = promise.data?.fast_delivery_max_minutes || null
  const data = isValidPincode(pincode) ? check.data : undefined
  return {
    minutes,
    pincode,
    check: data,
    fastHere: Boolean(minutes && data?.serviceable && data.fast_delivery_available),
    notServed: data?.serviceable === false,
  }
}

/** 1. Hero: headline, the two main actions and an honest delivery line. */
function Hero() {
  const { minutes, pincode, check, fastHere, notServed } = useDeliveryClaims()
  const fastLine = fastHere
    ? `Fast delivery to ${pincode}: ${check?.label}`
    : minutes && !notServed && !check
      ? `Fast delivery within ${minutes} mins where eligible`
      : null
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
          <ul className="mt-7 flex flex-wrap gap-x-6 gap-y-2 text-sm text-steel-200" aria-label="Delivery" data-testid="hero-delivery">
            {fastLine && (
              <li className="inline-flex items-center gap-2">
                <BoltIcon className="size-4 shrink-0 text-amber-400" />
                {fastLine}
              </li>
            )}
            {notServed ? (
              <li className="inline-flex items-center gap-2">
                <PinIcon className="size-4 shrink-0 text-amber-400" />
                {check?.message || `We don’t deliver to ${pincode} yet.`}
              </li>
            ) : (
              <li className="inline-flex items-center gap-2">
                <TruckIcon className="size-4 shrink-0 text-amber-400" />
                {check?.serviceable && !fastHere ? `Delivery to ${pincode}: ${check.label}` : 'Standard delivery across Bengaluru'}
              </li>
            )}
          </ul>
        </div>
        <div className="animate-rise [animation-delay:120ms]">
          <HeroArt className="mx-auto w-full max-w-[18rem] drop-shadow-2xl sm:max-w-md lg:max-w-xl" />
        </div>
      </div>
    </section>
  )
}

/**
 * 2. What the platform offers — only claims the system backs right now: fast delivery only with the
 * configured limit (and not for a PIN we don't serve), bulk pricing only when products have bulk
 * prices. Cash on delivery isn't listed: it is switched per shop, store and zone and decided at checkout.
 */
const LG_COLS: Record<number, string> = { 2: 'lg:grid-cols-2', 3: 'lg:grid-cols-3', 4: 'lg:grid-cols-4' }

function TrustStrip() {
  const { minutes, notServed } = useDeliveryClaims()
  // Same query as the bulk-buying rail (shared cache): are there products with bulk prices at all?
  const bulk = useProducts({ page_size: '8', bulk_pricing: 'true' })
  type Point = [string, string, ReactNode]
  const trust: Point[] = []
  if (minutes && !notServed) trust.push(['Fast delivery', `Within ${minutes} mins where eligible`, <BoltIcon key="b" />])
  trust.push(['Easy returns', 'Request from your orders', <ReturnIcon key="r" />])
  if (bulk.data?.results.length) trust.push(['Bulk pricing', 'Lower prices for bigger orders', <LayersIcon key="l" />])
  trust.push(['GST-inclusive prices', 'No surprises at checkout', <ReceiptIcon key="g" />])
  const odd = trust.length % 2 === 1
  return (
    <section aria-label="Why shop with us" className="relative z-10 -mt-6 sm:-mt-8">
      <ul className={`card grid grid-cols-2 divide-steel-100 p-2 lg:divide-x ${LG_COLS[trust.length] ?? 'lg:grid-cols-4'}`}>
        {trust.map(([title, text, icon], i) => (
          <li key={title} className={`flex items-center gap-2.5 rounded-xl p-2.5 sm:gap-3 sm:p-3 ${odd && i === trust.length - 1 ? 'col-span-2 lg:col-span-1' : ''}`}>
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
  // Without the category tree (API down) the groups still list the shop's departments from the
  // table, linking to the real category pages, so the section stays useful instead of an error box.
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
  const { pincode, check, fastHere } = useDeliveryClaims()
  return (
    <ProductRail
      title="Fast delivery to you"
      eyebrow="Arriving soon"
      subtitle={fastHere ? `${check?.label} to ${pincode} · from stores near you` : undefined}
      icon={<BoltIcon className="size-5 text-amber-400" />}
      params={{ fast_delivery: 'true', ordering: 'popular' }}
      viewAllHref="/products?fast_delivery=true"
      enabled={fastHere}
      hideOnError
      tone="dark"
    />
  )
}

const RULE_LINKS: Partial<Record<Collection['rule'], string>> = {
  best_sellers: '/products?ordering=popular',
  new_launches: '/products?ordering=newest',
  bulk_pricing: '/products?bulk_pricing=true',
}

/** At most this many general product rows (curated lists and their live fallbacks) on the page. */
export const HOME_MAIN_RAILS = 3

/**
 * 5. The general product rows, in the shop's order: its curated lists first (deals of the week,
 * best sellers, new launches…), then live lists it hasn't curated (best sellers, new arrivals) and
 * finally a grid of popular hardware. Capped at three so the page doesn't become a stack of rows;
 * the page spreads them out between the other sections.
 */
function mainRails(collections: Collection[]): ReactNode[] {
  const rules = new Set(collections.map((c) => c.rule))
  const curated = collections
    .filter((c) => c.rule !== 'bulk_pricing' && c.products.length > 0)
    .map((collection) => (
      <ProductStrip
        key={`collection-${collection.id}`}
        title={collection.name}
        eyebrow="Curated"
        subtitle={collection.description || undefined}
        products={collection.products}
        viewAllHref={RULE_LINKS[collection.rule]}
      />
    ))
  const live = [
    !rules.has('best_sellers') && (
      <ProductRail
        key="best-sellers"
        title="Best sellers"
        eyebrow="Most bought"
        params={{ bestseller: 'true', ordering: 'popular' }}
        viewAllHref="/products?ordering=popular"
        hideOnError
      />
    ),
    !rules.has('new_launches') && (
      <ProductRail
        key="new-arrivals"
        title="New arrivals"
        eyebrow="Just in"
        params={{ ordering: 'newest' }}
        viewAllHref="/products?ordering=newest"
        hideOnError
      />
    ),
    <ProductRail
      key="popular"
      title="Popular hardware"
      eyebrow="Customers’ picks"
      params={{ ordering: 'popular', in_stock: 'true' }}
      viewAllHref="/products?ordering=popular"
      layout="grid"
      hideOnError
    />,
  ].filter(Boolean) as ReactNode[]
  return [...curated, ...live].slice(0, HOME_MAIN_RAILS)
}

/** 6. Delivery, worded the way the engine works: fast where eligible (the configured limit), standard otherwise. */
function DeliveryBanner() {
  const { minutes, pincode, check, notServed } = useDeliveryClaims()
  const points: [ReactNode, string, string][] = [
    [<PinIcon key="p" />, 'Bengaluru', check?.serviceable ? `We deliver to ${pincode}` : 'Check your PIN code in the header'],
    ...(minutes && !notServed
      ? [[<BoltIcon key="b" />, `Fast delivery within ${minutes} mins`, 'Where your address, stock and riders allow'] as [ReactNode, string, string]]
      : []),
    [<TruckIcon key="t" />, 'Standard delivery', minutes && !notServed ? 'A delivery window when fast isn’t possible' : 'A delivery window for your address'],
  ]
  return (
    <section aria-labelledby="delivery-heading" className="my-8 animate-rise overflow-hidden rounded-3xl bg-ink-900 text-white">
      <div className="relative grid gap-6 p-6 sm:p-8 lg:grid-cols-[1fr_1.4fr] lg:items-center lg:p-10">
        <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 size-80 rounded-full bg-amber-500/15 blur-3xl" />
        <div className="relative">
          <p className="eyebrow text-amber-400">Delivery</p>
          <h2 id="delivery-heading" className="mt-1 text-2xl font-bold sm:text-3xl">
            {minutes && !notServed ? 'Fast hardware delivery across Bengaluru' : 'Hardware delivery across Bengaluru'}
          </h2>
          <p className="mt-2 text-sm text-steel-200">
            {notServed
              ? `${check?.message || `We don’t deliver to ${pincode} yet.`} Try another PIN code in the header.`
              : 'Choose your PIN code in the header to see the delivery time for your address. The time for your order is confirmed in the cart.'}
          </p>
        </div>
        <ul className={`relative grid gap-3 ${points.length === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
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

/** 7. Bulk buying — the shop's bulk list if it has one, else every product with bulk prices. */
function BulkBuyingRail({ collections }: { collections: Collection[] }) {
  const own = collections.filter((c) => c.rule === 'bulk_pricing' && c.products.length > 0).slice(0, 1)
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
      hideOnError
      tone="tinted"
    />
  )
}

/** 8. The shopping tools, kept out of the navigation. */
const AI_TOOLS: [string, string, string, ReactNode][] = [
  ['AI assistant', 'Describe the job, get the right parts', '/ai-assistant', <SparkIcon key="a" />],
  ['Image search', 'Snap a part to find it', '/image-search', <CameraIcon key="i" />],
  ['Voice search', 'Say what you need', '/voice', <MicIcon key="v" />],
  ['Project builder', 'A priced kit for your job', '/projects', <ClipboardIcon key="p" />],
  ['Quantity calculator', 'How many screws, plugs and more', '/quantity', <CalculatorIcon key="q" />],
  ['Compare products', 'Specs and prices side by side', '/compare', <CompareIcon key="c" />],
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
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 xl:grid-cols-6">
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

/** Recently viewed — slugs from this browser, products always loaded fresh. */
function useRecentProducts() {
  const slugs = useRecentlyViewed()
  const query = useProducts({ slugs: slugs.join(','), page_size: String(slugs.length || 1) }, { enabled: slugs.length > 0 })
  const bySlug = new Map((query.data?.results ?? []).map((p) => [p.slug, p]))
  return slugs.map((slug) => bySlug.get(slug)).filter((p): p is ProductSummary => Boolean(p))
}

/** More from the category of a saved item, or of the last product viewed (when the server has no picks). */
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
      hideOnError
    />
  )
}

/** The server's personal rows (buy again, from your orders, your project). Of its general rows only
 * "best value" is used: "popular now" would repeat the page's own best sellers / popular hardware. */
const PERSONAL_GROUPS = ['buy_again', 'recommended_for_you', 'complete_your_project']
const GENERAL_GROUPS = ['best_value']

/**
 * 9. For you: recently viewed, then at most two of the server's personal rows (buy again first) or,
 * without any, its "best value" row and a "recommended" row from the last viewed or saved category.
 */
function ForYou() {
  const recent = useRecentProducts()
  const recs = useHomeRecommendations()
  const has = (name: string) => (recs.data?.groups[name] ?? []).length > 0
  const personal = PERSONAL_GROUPS.filter(has).slice(0, 2)
  const order = personal.length ? personal : GENERAL_GROUPS.filter(has)
  return (
    <>
      <ProductStrip title="Recently viewed" eyebrow="Pick up where you left off" products={recent} />
      {recs.data && order.length > 0 && <RecommendationRails data={recs.data} order={order} />}
      {!personal.length && !recs.isPending && <RecommendedForYou recent={recent} />}
    </>
  )
}

/*
 * Page order: a calm rhythm instead of rows stacked on rows. Bands (trust, delivery, bulk, tools)
 * separate the product rows; every section hides itself when it has nothing to show or its data
 * can't be loaded, so an empty shop or a backend outage leaves no bare headings.
 */
export function HomePage() {
  usePageMeta(null, `${env.appName}: plywood, Fevicol, hinges, kitchen and wardrobe fittings, door locks, tools and safety gear delivered across Bengaluru.`)
  const collections = useCollections()
  const lists = collections.data ?? []
  const [first, second, third] = collections.isPending ? [] : mainRails(lists)
  return (
    <>
      <Hero />
      <div className="container-page">
        <TrustStrip />
        <ShopByGroup />
        <FastDeliveryRail />
        {first}
        <LiveOffersStrip />
        <ForYou />
        <DeliveryBanner />
        {second}
        {!collections.isPending && <BulkBuyingRail collections={lists} />}
        {third}
        <AiSection />
      </div>
    </>
  )
}
