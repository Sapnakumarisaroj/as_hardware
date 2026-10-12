import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { FullLogo } from '@/components/BrandLogo'
import { ChatIcon, MailIcon, PhoneIcon, PinIcon } from '@/components/icons'
import { InfoPage } from '@/features/company/InfoPage'
import { business } from '@/lib/business'

function Card({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="card flex gap-4 p-5" aria-label={title}>
      <span aria-hidden className="grid size-11 shrink-0 place-items-center rounded-full bg-amber-100 text-amber-700">
        {icon}
      </span>
      <div className="min-w-0">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-600">{title}</h2>
        <div className="mt-1 text-ink-950">{children}</div>
      </div>
    </section>
  )
}

/** The shop's real contact details from lib/business.ts; nothing here is invented or placeholder. */
export function ContactPage() {
  return (
    <InfoPage
      group="company"
      wide
      title="Contact"
      intro={`Call, email or visit ${business.name} for prices, bulk orders and help choosing the right fittings.`}
    >
      <div className="grid items-start gap-6 xl:grid-cols-[1fr_1.4fr]">
        <div className="card flex flex-col items-center p-6 text-center">
          <FullLogo className="w-full max-w-xs" loading="eager" />
          <h2 className="mt-4! text-2xl font-extrabold text-ink-950">{business.name}</h2>
          <p className="mt-1 text-ink-600">{business.tagline}</p>
        </div>

        <div className="space-y-4">
          <Card icon={<PinIcon className="size-5" />} title="Visit us">
            <address className="not-italic">
              <span className="block font-semibold">{business.name} </span>
              {business.addressLines.map((line) => (
                <span key={line} className="block">
                  {line},{' '}
                </span>
              ))}
              {business.country}.
            </address>
            <a href={business.directionsUrl} target="_blank" rel="noopener noreferrer" className="btn-secondary mt-3 inline-flex">
              Get directions<span className="sr-only"> (opens Google Maps)</span>
            </a>
          </Card>
          {business.phones.length > 0 && (
            <Card icon={<PhoneIcon className="size-5" />} title="Phone">
              {business.phones.map((phone) => (
                <a key={phone.number} href={phone.href} className="block w-fit text-lg font-bold hover:text-amber-700 hover:underline">
                  {phone.number}
                </a>
              ))}
            </Card>
          )}
          {business.email && (
            <Card icon={<MailIcon className="size-5" />} title="Email">
              <a href={business.emailHref} className="break-all text-lg font-bold hover:text-amber-700 hover:underline">
                {business.email}
              </a>
            </Card>
          )}
          {business.whatsappHref && (
            <Card icon={<ChatIcon className="size-5" />} title="WhatsApp">
              <a href={business.whatsappHref} target="_blank" rel="noopener noreferrer" className="text-lg font-bold hover:text-amber-700 hover:underline">
                Chat on WhatsApp ({business.whatsapp})
              </a>
            </Card>
          )}
          <p className="text-sm text-ink-600">
            Questions about an order? Open it from{' '}
            <Link to="/account/orders" className="font-semibold text-ink-950 underline">
              your orders
            </Link>
            .
          </p>
        </div>
      </div>
    </InfoPage>
  )
}
