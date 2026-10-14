import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { approvedCategories, productPage, productSummary } from '@/test/fixtures'
import { mockApi, paramsSent } from '@/test/mockApi'
import { renderRoute } from '@/test/utils'

/* Official business details (lib/business.ts), the three-column footer, and the company and policy pages. */

const ADDRESS = '264, 2nd Cross Road, Pete Krishnappa Layout, Kalkere, Bengaluru, Karnataka 560113, India'
const DIRECTIONS = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(ADDRESS)}`

const COMPANY = [
  ['About Us', '/about'],
  ['Contact', '/contact'],
  ['Price Lists', '/price-lists'],
  ['Knowledge Hub', '/knowledge-hub'],
  ['Shop by Category', '/shop-by-category'],
  ['FAQs', '/faq'],
]
const POLICY = [
  ['Refund Policy', '/policies/refund-policy'],
  ['Privacy Policy', '/policies/privacy-policy'],
  ['Terms of Service', '/policies/terms-of-service'],
  ['Shipping Policy', '/policies/shipping-policy'],
]

function api(products = [productSummary()]) {
  return mockApi({
    get: { '/categories/': approvedCategories, '/delivery/promise/': { fast_delivery_max_minutes: 60 }, '/products/': productPage(products) },
  })
}

describe('footer', () => {
  it('has the Company, Policy and Contact Information columns with real details', async () => {
    api()
    renderRoute('/about')
    await screen.findByRole('heading', { level: 1, name: 'About Us' })
    const footer = screen.getByRole('contentinfo')

    for (const [title, links] of [['Company', COMPANY], ['Policy', POLICY]] as const) {
      const column = within(footer).getByRole('navigation', { name: title })
      expect(within(column).getByRole('heading', { name: title })).toBeInTheDocument()
      const found = within(column).getAllByRole('link')
      expect(found.map((a) => [a.textContent, a.getAttribute('href')])).toEqual(links)
    }

    const contact = within(footer).getByRole('region', { name: 'Contact Information' })
    expect(within(contact).getByRole('link', { name: 'ashardwareplywood@gmail.com' })).toHaveAttribute('href', 'mailto:ashardwareplywood@gmail.com')
    expect(within(contact).getByRole('link', { name: '7338192616' })).toHaveAttribute('href', 'tel:7338192616')
    expect(contact).toHaveTextContent('AS Hardware and Plywood 264, 2nd Cross Road Pete Krishnappa Layout, Kalkere Bengaluru, Karnataka 560113 India')
    expect(within(contact).getByRole('link', { name: /Get Directions/ })).toHaveAttribute('href', DIRECTIONS)
    expect(footer).toHaveTextContent(`© ${new Date().getFullYear()} AS Hardware and Plywood. All rights reserved.`)
    // No large logo in the footer, and the unconfirmed second number is never shown.
    expect(within(footer).queryByRole('img')).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent('63631462556')
  })
})

describe('company and policy pages', () => {
  it.each([...COMPANY, ...POLICY])('%s (%s) opens a page with content', async (title, path) => {
    api()
    renderRoute(path)
    const heading = await screen.findByRole('heading', { level: 1, name: title })
    const article = heading.closest('article') as HTMLElement
    expect(within(article).getAllByRole('heading', { level: 2 }).length).toBeGreaterThan(0)
    // The page's own entry is marked as current in the side menu.
    expect(screen.getByRole('navigation', { name: /pages$/ }).querySelector('[aria-current="page"]')).toHaveTextContent(title)
    await waitFor(() => expect(document.title).toBe(`${title} | AS Hardware and Plywood`))
  })

  it('contact page shows the address and working phone, email and directions links', async () => {
    api()
    renderRoute('/contact')
    const article = (await screen.findByRole('heading', { level: 1, name: 'Contact' })).closest('article') as HTMLElement
    expect(article).toHaveTextContent(`AS Hardware and Plywood ${ADDRESS}.`)
    expect(within(article).getByRole('link', { name: '7338192616' })).toHaveAttribute('href', 'tel:7338192616')
    expect(within(article).getByRole('link', { name: 'ashardwareplywood@gmail.com' })).toHaveAttribute('href', 'mailto:ashardwareplywood@gmail.com')
    expect(within(article).getByRole('link', { name: /Get directions/ })).toHaveAttribute('href', DIRECTIONS)
    expect(within(article).getByRole('link', { name: /WhatsApp/ }).getAttribute('href')).toContain('https://wa.me/917338192616')
  })

  it('price lists show live catalogue prices for the chosen department', async () => {
    const http = api([productSummary({ name: 'Drill Machine 13mm', price: '2499.00', mrp: '2999.00' })])
    const { user } = renderRoute('/price-lists')
    const table = await screen.findByRole('table', { name: 'Plywood, MDF & HDHMR prices' })
    expect(within(table).getByRole('link', { name: 'Drill Machine 13mm' })).toBeInTheDocument()
    expect(table).toHaveTextContent('₹2,499')
    await user.click(screen.getByRole('button', { name: 'Power Tools & Accessories' }))
    await screen.findByRole('table', { name: 'Power Tools & Accessories prices' })
    expect(paramsSent(http.get, '/products/')).toContainEqual(expect.objectContaining({ category: 'power-tools', ordering: 'price' }))
    expect(screen.getByRole('link', { name: 'See all products with bulk prices' })).toHaveAttribute('href', '/products?bulk_pricing=true')
  })

  it('shop by category lists the four groups and all ten departments', async () => {
    api()
    renderRoute('/shop-by-category')
    await screen.findByRole('heading', { level: 1, name: 'Shop by Category' })
    for (const group of ['Wood & Adhesives', 'Furniture Hardware', 'Door & Glass Hardware', 'Tools & Safety']) {
      expect(screen.getByRole('heading', { level: 2, name: group })).toBeInTheDocument()
    }
    const departments = screen.getAllByRole('navigation', { name: /^Shop / }).flatMap((nav) => within(nav).getAllByRole('link'))
    expect(new Set(departments.map((a) => a.getAttribute('href'))).size).toBeGreaterThanOrEqual(10)
  })

  it('FAQ answers open on click', async () => {
    api()
    const { user } = renderRoute('/faq')
    const question = await screen.findByText('Can I return an item?')
    const details = question.closest('details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    await user.click(question)
    expect(details.open).toBe(true)
    expect(details).toHaveTextContent('within 7 days of delivery')
  })

  it('refund policy marks undecided rules instead of inventing them', async () => {
    api()
    renderRoute('/policies/refund-policy')
    await screen.findByRole('heading', { level: 1, name: 'Refund Policy' })
    const notes = screen.getAllByRole('note')
    expect(notes.length).toBeGreaterThanOrEqual(2)
    expect(notes.map((n) => n.textContent).join(' ')).toMatch(/Refund timelines/)
    // Cancellation rules are decided (5-minute window, ₹200 COD fee): stated as policy, no longer a pending note.
    expect(notes.map((n) => n.textContent).join(' ')).not.toMatch(/cancellation charges/i)
    expect(screen.getByText(/within 5 minutes of placing/)).toBeInTheDocument()
    expect(screen.getByText(/cancellation fee of ₹200 applies/)).toBeInTheDocument()
  })
})

describe('branding', () => {
  it('shows the official logo on the login page', async () => {
    api()
    renderRoute('/login')
    const home = await screen.findByRole('link', { name: 'AS Hardware and Plywood home' })
    expect(within(home).getByRole('img', { name: 'AS Hardware and Plywood' })).toHaveAttribute('src', '/images/as-hardware-logo-symbol.png')
    expect(home).toHaveTextContent('Hardware and Plywood')
  })

  it('shows the AS symbol with the name below it in the storefront header, at its own proportions', async () => {
    api()
    renderRoute('/about')
    await screen.findByRole('heading', { level: 1, name: 'About Us' })
    const logo = within(screen.getByRole('banner')).getByRole('link', { name: 'AS Hardware and Plywood home' }).querySelector('img')
    expect(logo).toHaveAttribute('src', '/images/as-hardware-logo-symbol.png')
    expect(logo).toHaveAttribute('width', '421')
    expect(logo).toHaveAttribute('height', '360')
    expect(logo?.className).toContain('w-auto')
    expect(logo?.className).not.toContain('rounded-full')
  })
})
