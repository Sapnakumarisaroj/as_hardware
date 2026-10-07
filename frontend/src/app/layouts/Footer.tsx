import { Link } from 'react-router'

import { useCategories } from '@/features/catalog/api'
import { env } from '@/lib/env'

export function Footer() {
  const categories = useCategories()
  const link = 'text-sm text-steel-200 hover:text-amber-500'
  return (
    <footer className="mt-12 bg-ink-900 text-white">
      <div className="container-page grid gap-8 py-10 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <p className="text-lg font-extrabold">{env.appName}</p>
          <p className="mt-2 max-w-xs text-sm text-steel-200">
            Plywood, Fevicol, furniture fittings, door locks, tools and safety gear from local stores. Prices include GST.
          </p>
        </div>
        <nav aria-label="Shop">
          <h2 className="text-sm font-bold uppercase tracking-wide text-steel-400">Shop</h2>
          <ul className="mt-3 space-y-2">
            {categories.data?.filter((c) => c.product_count !== 0).slice(0, 6).map((category) => (
              <li key={category.id}>
                <Link to={`/c/${category.slug}`} className={link}>
                  {category.name}
                </Link>
              </li>
            ))}
            <li>
              <Link to="/products" className={link}>
                All products
              </Link>
            </li>
            <li>
              <Link to="/brands" className={link}>
                Brands
              </Link>
            </li>
          </ul>
        </nav>
        <nav aria-label="Your account">
          <h2 className="text-sm font-bold uppercase tracking-wide text-steel-400">Your account</h2>
          <ul className="mt-3 space-y-2">
            <li>
              <Link to="/account" className={link}>
                My account
              </Link>
            </li>
            <li>
              <Link to="/account/orders" className={link}>
                Orders
              </Link>
            </li>
            <li>
              <Link to="/wishlist" className={link}>
                Wishlist
              </Link>
            </li>
            <li>
              <Link to="/cart" className={link}>
                Cart
              </Link>
            </li>
          </ul>
        </nav>
        <div>
          <h2 className="text-sm font-bold uppercase tracking-wide text-steel-400">Help</h2>
          <ul className="mt-3 space-y-2 text-sm text-steel-200">
            {env.supportPhone && (
              <li>
                Call <a href={`tel:${env.supportPhone}`} className="hover:text-amber-500">{env.supportPhone}</a>
              </li>
            )}
            {env.supportWhatsApp && (
              <li>
                WhatsApp{' '}
                <a href={`https://wa.me/${env.supportWhatsApp.replace(/\D/g, '')}`} className="hover:text-amber-500">
                  {env.supportWhatsApp}
                </a>
              </li>
            )}
            <li>
              <Link to="/ai-assistant" className="hover:text-amber-500">
                Ask the AI assistant
              </Link>
            </li>
            <li>
              <Link to="/image-search" className="hover:text-amber-500">
                Search with a photo
              </Link>
            </li>
            <li>
              <Link to="/voice" className="hover:text-amber-500">
                Shop by voice
              </Link>
            </li>
            <li>
              <Link to="/projects" className="hover:text-amber-500">
                Project builder
              </Link>
            </li>
            <li>
              <Link to="/quantity" className="hover:text-amber-500">
                Quantity calculator
              </Link>
            </li>
            <li>
              <Link to="/bundles" className="hover:text-amber-500">
                Kits and bundles
              </Link>
            </li>
            <li>
              <Link to="/budget" className="hover:text-amber-500">
                Shop within a budget
              </Link>
            </li>
            <li>
              <Link to="/account/returns" className="hover:text-amber-500">
                Returns
              </Link>
            </li>
            <li>Delivery times are calculated for your PIN code and confirmed at checkout for your address.</li>
          </ul>
        </div>
      </div>
      <div className="border-t border-ink-800">
        <p className="container-page py-4 text-xs text-steel-400">
          © {new Date().getFullYear()} {env.appName}
        </p>
      </div>
    </footer>
  )
}
