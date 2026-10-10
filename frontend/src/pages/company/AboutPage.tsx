import { Link } from 'react-router'

import { NAV_GROUPS } from '@/features/catalog/navGroups'
import { InfoPage } from '@/features/company/InfoPage'
import { business } from '@/lib/business'

const BUYERS = [
  ['Homeowners', 'Find fittings, locks and tools for repairs and home projects, with clear prices and delivery times before you order.'],
  ['Carpenters', 'Boards, adhesives, hinges, channels and handles in the sizes and finishes a job needs, with bulk prices on larger quantities.'],
  ['Contractors', 'Order project quantities, ask for a quotation on large orders and keep every order and invoice in your account.'],
  ['Interior designers', 'Compare options side by side and plan kitchens and wardrobes with the project builder and quantity calculator.'],
  ['Businesses', 'Add your business name and GSTIN to your profile so they are printed on your invoices.'],
] as const

/** /about — who the shop is and how buying works, from the shop's own details (no invented history or claims). */
export function AboutPage() {
  return (
    <InfoPage
      group="company"
      title="About Us"
      intro={`${business.name}: ${business.tagline.toLowerCase()} for furniture, kitchens, wardrobes, doors and related projects in Bengaluru.`}
    >
      <h2>Who we are</h2>
      <p>
        {business.name} provides hardware and interior-fitting products for furniture, kitchens, wardrobes, doors and related
        projects. Our shop is at {business.addressText}.
      </p>

      <h2>Our product categories</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {NAV_GROUPS.map((group) => (
          <section key={group.slug} aria-labelledby={`about-${group.slug}`} className="rounded-xl bg-white p-4 ring-1 ring-steel-200">
            <h3 id={`about-${group.slug}`} className="mt-0! text-base font-bold text-ink-950">
              <Link to={`/shop/${group.slug}`} className="hover:text-amber-700">
                {group.name}
              </Link>
            </h3>
            <ul className="mt-2 space-y-1 text-sm">
              {group.departments.map(([slug, name]) => (
                <li key={slug}>
                  <Link to={`/c/${slug}`} className="text-ink-800 underline-offset-2 hover:text-amber-700 hover:underline">
                    {name}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <h2>Who we serve</h2>
      <dl className="mt-4 space-y-3">
        {BUYERS.map(([who, how]) => (
          <div key={who} className="border-l-4 border-amber-500 pl-4">
            <dt className="font-semibold text-ink-950">{who}</dt>
            <dd className="text-ink-700">{how}</dd>
          </div>
        ))}
      </dl>

      <h2>How to shop</h2>
      <ol>
        <li>
          <strong>Browse</strong> the <Link to="/shop-by-category">categories</Link> or search by product, brand or job, by
          photo or by voice.
        </li>
        <li>
          <strong>Choose the variant</strong> (size, finish or pack) on the product page. Its price, MRP, any bulk prices and
          stock are shown for the variant you pick.
        </li>
        <li>
          <strong>Check delivery</strong> for your PIN code: the page shows whether we deliver there and the estimated time.
        </li>
        <li>
          <strong>Add to cart</strong>, where offers and bulk prices are applied and you can request a quotation for large
          orders.
        </li>
        <li>
          <strong>Check out</strong> with your delivery address and a payment option available for your order, then follow
          the order in <Link to="/account/orders">your orders</Link>.
        </li>
      </ol>

      <h2>Delivery</h2>
      <p>
        We offer standard delivery across our Bengaluru service area. Fast delivery is available only when your address,
        the stock at a nearby store and the calculated delivery time allow it, so it is not available for every address or
        order. The delivery time for your address is shown on product pages once you enter your PIN code, and confirmed at
        checkout. See the <Link to="/policies/shipping-policy">Shipping Policy</Link> for details.
      </p>

      <h2>Get in touch</h2>
      <p>
        Questions about a product, a large order or a delivery? <Link to="/contact">Contact us</Link> by phone or email, or
        visit the shop.
      </p>
    </InfoPage>
  )
}
