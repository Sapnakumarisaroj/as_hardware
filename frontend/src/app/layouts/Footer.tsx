import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { ChevronRightIcon } from '@/components/icons'
import { CompareTray } from '@/features/compare/CompareTray'
import { COMPANY_LINKS, POLICY_LINKS } from '@/features/company/links'
import { business } from '@/lib/business'

const heading = 'text-xl font-bold tracking-tight text-ink-950 lg:text-2xl'
const focus = 'rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-950'
const textLink = `font-semibold text-ink-950 underline decoration-ink-950/30 underline-offset-4 transition-colors hover:decoration-ink-950 ${focus}`

function LinkColumn({ title, links }: { title: string; links: readonly (readonly [string, string])[] }) {
  return (
    <nav aria-label={title}>
      <h2 className={heading}>{title}</h2>
      <ul className="mt-4 space-y-1 md:mt-6 md:space-y-2">
        {links.map(([label, to]) => (
          <li key={to}>
            <Link
              to={to}
              className={`group inline-flex items-center gap-2 py-1.5 text-[0.95rem] font-medium text-ink-950 transition-colors hover:text-ink-700 ${focus}`}
            >
              <ChevronRightIcon aria-hidden className="size-4 shrink-0 transition-transform group-hover:translate-x-0.5" />
              <span className="underline-offset-4 group-hover:underline">{label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="font-bold">{label}</dt>
      <dd className="mt-1">{children}</dd>
    </div>
  )
}

/**
 * Golden three-column footer: company pages, policies, contact details (lib/business.ts). Columns
 * stack on phones, Company and Policy share a row on small tablets.
 */
export function Footer() {
  return (
    <footer className="mt-12 bg-amber-500 text-ink-950">
      <div className="container-page grid gap-x-8 gap-y-10 py-10 sm:grid-cols-2 md:grid-cols-[1fr_1fr_1.35fr] md:py-14 lg:gap-x-16">
        <LinkColumn title="Company" links={COMPANY_LINKS} />
        <LinkColumn title="Policy" links={POLICY_LINKS} />

        <section aria-labelledby="footer-contact" className="sm:col-span-2 md:col-span-1">
          <h2 id="footer-contact" className={heading}>
            Contact Information
          </h2>
          <dl className="mt-4 space-y-5 text-[0.95rem] leading-relaxed md:mt-6">
            {business.email && (
              <Detail label="Email:">
                <a href={business.emailHref} className={`${textLink} [overflow-wrap:anywhere]`}>
                  {business.email}
                </a>
              </Detail>
            )}
            {business.phones.length > 0 && (
              <Detail label="Phone:">
                {business.phones.map((phone) => (
                  <a key={phone.number} href={phone.href} className={`${textLink} block w-fit`}>
                    {phone.number}
                  </a>
                ))}
              </Detail>
            )}
            <Detail label="Address:">
              <address className="not-italic">
                <span className="block font-semibold">{business.name} </span>
                {business.addressLines.map((line) => (
                  <span key={line} className="block">
                    {line}{' '}
                  </span>
                ))}
                <span className="block">{business.country}</span>
              </address>
              <a
                href={business.directionsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={`mt-3 inline-flex items-center gap-1.5 rounded-lg bg-ink-950 px-3.5 py-2 text-sm font-semibold text-white transition-colors hover:bg-ink-800 ${focus}`}
              >
                Get Directions
                <ChevronRightIcon aria-hidden className="size-4" />
                <span className="sr-only"> (opens Google Maps)</span>
              </a>
            </Detail>
          </dl>
        </section>
      </div>
      <div className="border-t border-ink-950/15">
        <p className="container-page py-4 text-sm text-ink-900">
          © {new Date().getFullYear()} {business.name}. All rights reserved.
        </p>
      </div>
      {/* Fixed to the bottom of the screen; rendered here so its spacer sits under the footer. */}
      <CompareTray />
    </footer>
  )
}
