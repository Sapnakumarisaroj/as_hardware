import type { ReactNode } from 'react'
import { NavLink } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { AlertIcon } from '@/components/icons'
import { usePageMeta } from '@/lib/usePageMeta'

import { COMPANY_LINKS, POLICY_LINKS } from './links'

interface Props {
  group: 'company' | 'policies'
  title: string
  /** One or two sentences under the title; also the page's meta description. */
  intro: string
  children: ReactNode
  /** Set on the policy pages: the content is based on how the shop works today, not a legal review. */
  note?: ReactNode
  /** Full content width (grids and tables) instead of a readable text column. */
  wide?: boolean
}

/** Shared shell for the company and policy pages: breadcrumbs, title, sibling-page menu and readable text. */
export function InfoPage({ group, title, intro, children, note, wide = false }: Props) {
  usePageMeta(title, intro)
  const links = group === 'company' ? COMPANY_LINKS : POLICY_LINKS
  const groupLabel = group === 'company' ? 'Company' : 'Policies'
  return (
    <div className="container-page py-6">
      <Breadcrumbs items={[{ label: groupLabel }, { label: title }]} />
      <div className="mt-4 grid gap-8 lg:grid-cols-[14rem_1fr] lg:gap-12">
        <nav aria-label={`${groupLabel} pages`} className="order-last lg:order-first">
          <h2 className="eyebrow">{groupLabel}</h2>
          <ul className="mt-3 grid grid-cols-2 gap-1 sm:grid-cols-3 lg:sticky lg:top-40 lg:grid-cols-1">
            {links.map(([label, to]) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end
                  className={({ isActive }) =>
                    `block rounded-lg px-3 py-2 text-sm transition-colors ${
                      isActive ? 'bg-ink-950 font-semibold text-white' : 'text-ink-700 hover:bg-steel-100 hover:text-ink-950'
                    }`
                  }
                >
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <article className="min-w-0">
          <div className="border-b border-steel-200 pb-6">
            <h1 className="text-3xl font-extrabold tracking-tight text-ink-950 sm:text-4xl">{title}</h1>
            <p className="mt-3 max-w-3xl text-base text-ink-700 sm:text-lg">{intro}</p>
            {note && <p className="mt-3 max-w-3xl text-sm text-ink-600">{note}</p>}
          </div>
          <div className={`prose-page mt-6 ${wide ? '' : 'max-w-3xl'}`}>{children}</div>
        </article>
      </div>
    </div>
  )
}

/** A rule the owner still has to decide: shown honestly instead of an invented rule. */
export function PendingDecision({ children }: { children: ReactNode }) {
  return (
    <div role="note" className="my-4 flex gap-3 rounded-xl border border-amber-500/40 bg-amber-50 p-4 text-sm text-ink-800">
      <AlertIcon className="mt-0.5 size-5 shrink-0 text-amber-700" />
      <div>
        <p className="font-semibold text-ink-950">Being finalised</p>
        <div className="mt-1">{children}</div>
      </div>
    </div>
  )
}
