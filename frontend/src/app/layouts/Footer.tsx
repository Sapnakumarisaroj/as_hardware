import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { ChatIcon, ClockIcon, MailIcon, PhoneIcon, PinIcon } from '@/components/icons'
import { useNavGroups } from '@/features/catalog/navGroups'
import { CompareTray } from '@/features/compare/CompareTray'
import { env } from '@/lib/env'

const link = 'text-sm text-steel-200 transition-colors hover:text-amber-400'

function Column({ title, label, children }: { title: string; label?: string; children: ReactNode }) {
  return (
    <nav aria-label={label ?? title}>
      <h2 className="text-xs font-semibold uppercase tracking-[0.12em] text-steel-400">{title}</h2>
      <ul className="mt-3 space-y-2">{children}</ul>
    </nav>
  )
}

function Item({ to, children }: { to: string; children: ReactNode }) {
  return (
    <li>
      <Link to={to} className={link}>
        {children}
      </Link>
    </li>
  )
}

/** Only pages and facts the shop actually has: no placeholder policies or contact details. */
export function Footer() {
  const { groups } = useNavGroups()
  const whatsapp = env.supportWhatsApp.replace(/\D/g, '')
  return (
    <footer className="mt-12 bg-ink-950 text-white">
      <div className="container-page grid gap-8 py-12 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr_1fr]">
        <div>
          <Link to="/" className="inline-flex items-center gap-2 text-lg font-extrabold">
            <img src="/favicon.svg" alt="" className="size-8" />
            {env.appName}
          </Link>
          <p className="mt-3 max-w-xs text-sm text-steel-200">
            Plywood, Fevicol, furniture fittings, door and glass hardware, tools and safety gear, delivered across Bengaluru.
          </p>
          <ul className="mt-4 space-y-2 text-sm text-steel-200" aria-label="Contact">
            <li className="flex items-center gap-2">
              <PinIcon className="size-4 shrink-0 text-amber-400" />
              Service area: Bengaluru
            </li>
            {env.storeHours && (
              <li className="flex items-center gap-2">
                <ClockIcon className="size-4 shrink-0 text-amber-400" />
                {env.storeHours}
              </li>
            )}
            {env.supportPhone && (
              <li className="flex items-center gap-2">
                <PhoneIcon className="size-4 shrink-0 text-amber-400" />
                <a href={`tel:${env.supportPhone}`} className="hover:text-amber-400">
                  {env.supportPhone}
                </a>
              </li>
            )}
            {whatsapp && (
              <li className="flex items-center gap-2">
                <ChatIcon className="size-4 shrink-0 text-amber-400" />
                <a href={`https://wa.me/${whatsapp}`} className="hover:text-amber-400">
                  WhatsApp {env.supportWhatsApp}
                </a>
              </li>
            )}
            {env.supportEmail && (
              <li className="flex items-center gap-2">
                <MailIcon className="size-4 shrink-0 text-amber-400" />
                <a href={`mailto:${env.supportEmail}`} className="hover:text-amber-400">
                  {env.supportEmail}
                </a>
              </li>
            )}
          </ul>
        </div>

        <Column title="Shop">
          {groups.map((group) => (
            <Item key={group.slug} to={group.href}>
              {group.name}
            </Item>
          ))}
          <Item to="/products">All products</Item>
          <Item to="/brands">Brands</Item>
          <Item to="/products?ordering=discount">Deals</Item>
          <Item to="/products?ordering=newest">New arrivals</Item>
        </Column>

        <Column title="Customer support">
          <Item to="/account/orders">Track your orders</Item>
          <Item to="/account/returns">Returns</Item>
          <Item to="/notifications">Notifications</Item>
          <Item to="/ai-assistant">Ask the AI assistant</Item>
          <Item to="/image-search">Search with a photo</Item>
          <Item to="/voice">Shop by voice</Item>
        </Column>

        <Column title="Your account">
          <Item to="/account">My account</Item>
          <Item to="/wishlist">Wishlist</Item>
          <Item to="/cart">Cart</Item>
          <Item to="/projects">Project builder</Item>
          <Item to="/quantity">Quantity calculator</Item>
          <Item to="/bundles">Kits and bundles</Item>
        </Column>

        <div>
          <h2 className="text-xs font-semibold uppercase tracking-[0.12em] text-steel-400">Policies</h2>
          <ul className="mt-3 space-y-2 text-sm text-steel-200">
            <li>Prices include GST</li>
            <li>Cash on delivery on eligible orders</li>
            <li>Delivery time confirmed for your address at checkout</li>
            <li>
              Returns: request from{' '}
              <Link to="/account/orders" className="underline hover:text-amber-400">
                your orders
              </Link>
            </li>
          </ul>
        </div>
      </div>
      <div className="border-t border-white/10">
        <p className="container-page flex flex-wrap items-center justify-between gap-2 py-4 text-xs text-steel-400">
          <span>
            © {new Date().getFullYear()} {env.appName}
          </span>
          <span>Delivering across Bengaluru</span>
        </p>
      </div>
      {/* Fixed to the bottom of the screen; rendered here so its spacer sits under the footer. */}
      <CompareTray />
    </footer>
  )
}
