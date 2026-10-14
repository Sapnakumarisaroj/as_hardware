import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { ChevronDownIcon } from '@/components/icons'
import { InfoPage } from '@/features/company/InfoPage'
import { business } from '@/lib/business'

type Faq = [question: string, answer: ReactNode]

/** Answers follow how ordering, payment, delivery and returns work in the system today. */
const SECTIONS: [title: string, faqs: Faq[]][] = [
  [
    'Ordering',
    [
      [
        'How do I place an order?',
        <>
          Choose a product and its variant (size, finish or pack), add it to your cart and go to checkout. Pick your delivery
          address and a payment option and place the order. You can follow it in <Link to="/account/orders">your orders</Link>.
        </>,
      ],
      [
        'Do I need an account?',
        'Yes. You need an account to check out, so we can keep your addresses, orders, invoices and returns together.',
      ],
      [
        'Can I cancel my order?',
        <>
          Yes, from <Link to="/account/orders">your orders</Link>, within 5 minutes of placing it and before it is packed.
          After that, contact us; we can still cancel it if it hasn’t left the store. Cancelling a cash-on-delivery order we
          have started preparing costs ₹200, added to your next order. See the{' '}
          <Link to="/policies/refund-policy">Refund Policy</Link>.
        </>,
      ],
      [
        'How do I get a price for a large order?',
        <>
          Add the items to your cart and choose <strong>Request a bulk quote</strong>. We reply with quoted prices and a
          validity date under <Link to="/account/quotes">My quotes</Link>, and you can accept and order. See{' '}
          <Link to="/price-lists">Price Lists</Link>.
        </>,
      ],
      [
        'Can I get a GST invoice?',
        'Add your business name and GSTIN to your profile or delivery address and they will appear on your invoice. You can download the invoice from the order page.',
      ],
    ],
  ],
  [
    'Prices and payment',
    [
      ['Do prices include GST?', 'Yes. All prices include GST. The MRP is shown next to the price for comparison.'],
      [
        'How do bulk prices, offers and coupons work?',
        'Bulk prices apply automatically when you buy enough units. Automatic offers are applied in the cart, and you can add one coupon per order. The cart shows every discount before you pay.',
      ],
      [
        'Which payment options are available?',
        'Checkout shows the options for your order. Cash on delivery is available on eligible orders up to ₹10,000, and can depend on the store and area serving your address. Online payment (UPI, card or net banking) is offered when it is enabled for the shop.',
      ],
      [
        'How do I pay for cash on delivery orders?',
        'Pay the delivery partner in cash or by UPI to the store when your order arrives.',
      ],
      [
        'What are credits?',
        'Credits are store credit, for example cashback or a reward. They can pay up to 20% of an order (not the delivery fee), expire 90 days after they are earned and can’t be exchanged for cash. Your balance is in your wallet.',
      ],
    ],
  ],
  [
    'Delivery',
    [
      [
        'Where do you deliver?',
        'Across our Bengaluru service area. Enter your PIN code on any product page to check delivery to your address.',
      ],
      [
        'How fast is delivery?',
        'Standard delivery is available across the service area, with a delivery window shown at checkout. Fast delivery is offered only when your address, stock at a nearby store and an available delivery partner allow it; we then show the calculated time for your address. It is not available for every address or order.',
      ],
      [
        'Is there a delivery charge?',
        'Any delivery fee is shown in your cart and at checkout before you pay. Orders above a minimum value, and some offers, get free delivery.',
      ],
      [
        'What is the delivery code?',
        'When your order is out for delivery, your order page shows a 6-digit code. Give it to the delivery partner at handover; it makes sure the order reaches the right person.',
      ],
      [
        'Why did my order arrive in more than one delivery?',
        'Larger orders can come from more than one store. Each delivery is shown and tracked separately on your order page.',
      ],
    ],
  ],
  [
    'Returns and refunds',
    [
      [
        'Can I return an item?',
        <>
          Yes, within 7 days of delivery, from the order in <Link to="/account/orders">your orders</Link>. Choose the items,
          quantities and a reason. Some products can’t be returned; you are told when you request the return.
        </>,
      ],
      [
        'How will I get my refund?',
        'After we receive the returned items, online payments are refunded to the original payment method and cash on delivery orders are refunded by the store in cash or UPI. Credits you used come back as credits.',
      ],
      [
        'Is the delivery fee refunded?',
        'Not for returns. If an order is cancelled before delivery, the full amount you paid online is refunded.',
      ],
    ],
  ],
]

/** /faq — grouped questions with expandable answers (native <details>, keyboard accessible). */
export function FaqPage() {
  return (
    <InfoPage group="company" title="FAQs" intro="Answers to common questions about ordering, payment, delivery and returns.">
      {SECTIONS.map(([title, faqs]) => (
        <section key={title} aria-labelledby={`faq-${title}`}>
          <h2 id={`faq-${title}`}>{title}</h2>
          <div className="mt-3 divide-y divide-steel-200 overflow-hidden rounded-xl bg-white ring-1 ring-steel-200">
            {faqs.map(([question, answer]) => (
              <details key={question} className="group">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3.5 font-semibold text-ink-950 hover:bg-steel-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-amber-500 [&::-webkit-details-marker]:hidden">
                  {question}
                  <ChevronDownIcon aria-hidden className="size-5 shrink-0 text-ink-600 transition-transform group-open:rotate-180" />
                </summary>
                <div className="px-4 pb-4 text-ink-700">{answer}</div>
              </details>
            ))}
          </div>
        </section>
      ))}
      <h2>Still have a question?</h2>
      <p>
        Call <a href={business.phoneHref}>{business.phone}</a>, email <a href={business.emailHref}>{business.email}</a> or see{' '}
        <Link to="/contact">Contact</Link>.
      </p>
    </InfoPage>
  )
}
