import { Link } from 'react-router'

import { InfoPage, PendingDecision } from '@/features/company/InfoPage'
import { business } from '@/lib/business'

/*
 * The four policies describe how the website and shop work today (orders, returns, refunds, delivery
 * and data handling as built). Rules the owner has not decided yet are shown as "Being finalised"
 * notes instead of invented terms. None of this has had a legal review.
 */

const UPDATED = '10 October 2026'

function PolicyNote() {
  return (
    <>
      Last updated {UPDATED}. This page describes how ordering works on our website today. Questions?{' '}
      <Link to="/contact" className="font-semibold text-ink-950 underline">
        Contact us
      </Link>
      .
    </>
  )
}

function ContactLine() {
  return (
    <p>
      {business.name}, {business.addressText}. Phone{' '}
      <a href={business.phoneHref}>{business.phone}</a>, email <a href={business.emailHref}>{business.email}</a>.
    </p>
  )
}

/** /policies/refund-policy — cancellations, returns and refunds as the order system handles them. */
export function RefundPolicyPage() {
  return (
    <InfoPage
      group="policies"
      title="Refund Policy"
      intro="How to cancel an order, return items and get your money back."
      note={<PolicyNote />}
    >
      <h2>Cancelling an order</h2>
      <ul>
        <li>
          You can cancel an order yourself from <Link to="/account/orders">your orders</Link> until it is packed, that is
          while it is placed, confirmed or being prepared. We ask for a short reason.
        </li>
        <li>
          Once an order is packed it can’t be cancelled online. Contact us quickly: we can still cancel it as long as it hasn’t
          left the store.
        </li>
        <li>
          When an order is cancelled, any coupon and credits you used are given back. If you paid online, the full amount is
          refunded to your original payment method. For cash on delivery nothing has been paid.
        </li>
        <li>Online orders that are not paid within 30 minutes are cancelled automatically.</li>
      </ul>
      <PendingDecision>Any cancellation charges, and a deadline for cancelling packed orders, are not set yet.</PendingDecision>

      <h2>Returns</h2>
      <ul>
        <li>
          You can request a return within <strong>7 days of delivery</strong>, from the order in{' '}
          <Link to="/account/orders">your orders</Link>.
        </li>
        <li>
          Choose the items and quantities to return and the reason: damaged, defective, wrong item, not as described, no longer
          needed or another reason. You can return part of an order.
        </li>
        <li>Some products can’t be returned. If an item can’t be returned, you will be told when you request the return.</li>
        <li>
          We review each request and approve or reject it. A rejection always comes with the reason. You can withdraw a
          request while it is waiting for review.
        </li>
        <li>
          After approval we arrange collection by our delivery partner or a drop-off at the store, and tell you which.
        </li>
      </ul>
      <PendingDecision>
        The condition required for returned items (for example unused and in original packaging), any restocking or
        pickup charges, and the list of non-returnable products are not set yet.
      </PendingDecision>

      <h2>Refunds</h2>
      <ul>
        <li>We start the refund when we receive the returned items.</li>
        <li>
          You get back what you actually paid for those items, after any offer, coupon and credit discounts. The delivery fee
          is not refunded on returns.
        </li>
        <li>
          <strong>Online payments</strong> are refunded to the original payment method through the payment provider.
        </li>
        <li>
          <strong>Cash on delivery orders</strong> are refunded by the store in cash or by UPI.
        </li>
        <li>
          <strong>Credits</strong> used on returned items come back as credits with their original expiry date. Credits that
          have expired are not restored, and credits are never paid out as cash.
        </li>
        <li>
          You can follow each return and refund in <Link to="/account/returns">your returns</Link>.
        </li>
      </ul>
      <PendingDecision>
        Refund timelines (how quickly online and cash-on-delivery refunds are completed) are not set yet. Your bank or
        payment app may take additional time to show an online refund.
      </PendingDecision>

      <h2>Contact</h2>
      <ContactLine />
    </InfoPage>
  )
}

/** /policies/shipping-policy — where and how the delivery engine delivers. */
export function ShippingPolicyPage() {
  return (
    <InfoPage
      group="policies"
      title="Shipping Policy"
      intro="Where we deliver, how delivery times are worked out, delivery charges and what happens at your door."
      note={<PolicyNote />}
    >
      <h2>Where we deliver</h2>
      <p>
        We deliver within our <strong>Bengaluru service area</strong>. Enter your PIN code on a product page or choose your
        delivery address at checkout to see whether we deliver there. We can’t accept orders for addresses outside the service
        area.
      </p>

      <h2>Delivery options and times</h2>
      <ul>
        <li>
          <strong>Standard delivery</strong> is available across the service area. Orders are sent out in batches during
          store hours, and checkout shows your delivery window.
        </li>
        <li>
          <strong>Fast delivery</strong> is offered only when your address, stock at a nearby store, store hours and an
          available delivery partner allow it. When it is available we show the calculated time for your address. It is not
          available for every address or order.
        </li>
        <li>
          Delivery times are estimates calculated from preparation time and distance. If an order is running late, we tell you.
        </li>
        <li>
          Large orders may come from more than one store, in up to three separate deliveries. Each one is shown and tracked
          on your order page.
        </li>
      </ul>

      <h2>Delivery charges</h2>
      <p>
        Any delivery fee is shown in your cart and at checkout before you pay. Orders above a minimum value, and some offers,
        qualify for free delivery. Credits can’t be used to pay the delivery fee.
      </p>
      <PendingDecision>
        The standard delivery fee and the free-delivery order value are being confirmed. Your cart and checkout always show
        the exact charge for your order.
      </PendingDecision>

      <h2>Receiving your order</h2>
      <ul>
        <li>
          When your delivery is on its way, your order page shows a <strong>6-digit delivery code</strong>. Give it to the
          delivery partner at handover; without it the delivery can’t be completed.
        </li>
        <li>The delivery partner may take a photo as proof of delivery.</li>
        <li>For cash on delivery, pay the delivery partner in cash or by UPI to the store.</li>
        <li>Please check the items at delivery. Report damaged or wrong items with a return request (see the Refund Policy).</li>
      </ul>

      <h2>If a delivery can’t be completed</h2>
      <p>
        If we can’t deliver, for example because nobody is available or the address is wrong, the items go back to the store
        and we contact you to deliver again or cancel the order.
      </p>
      <PendingDecision>Charges for a second delivery attempt are not set yet.</PendingDecision>

      <h2>Payment at delivery</h2>
      <p>
        Cash on delivery is available on eligible orders up to an order value of ₹10,000. Availability can also depend on the
        store and area serving your address. Checkout shows the payment options for your order.
      </p>

      <h2>Contact</h2>
      <ContactLine />
    </InfoPage>
  )
}

/** /policies/privacy-policy — the personal data the website actually stores and why. */
export function PrivacyPolicyPage() {
  return (
    <InfoPage
      group="policies"
      title="Privacy Policy"
      intro="What personal information our website collects, how we use it and the choices you have."
      note={<PolicyNote />}
    >
      <h2>Who we are</h2>
      <ContactLine />

      <h2>What we collect</h2>
      <ul>
        <li>
          <strong>Account details:</strong> name, email, mobile number and, if you add them, a profile photo, buyer type,
          business name and GSTIN.
        </li>
        <li>
          <strong>Addresses:</strong> delivery addresses, contact names and numbers, and an optional pin on the map.
        </li>
        <li>
          <strong>Orders:</strong> your orders, payments, returns, refunds, quotations, wishlist and credits.
        </li>
        <li>
          <strong>Messages:</strong> support conversations (including WhatsApp, if you write to us there) and the
          notifications we send you.
        </li>
        <li>
          <strong>Delivery records:</strong> delivery status and times, and a proof-of-delivery photo when one is taken.
        </li>
        <li>
          <strong>Shopping assistants:</strong> your conversations with the AI assistant. For voice search we keep the text
          of what you said; the recording itself is discarded once it has been transcribed. For photo search we keep the
          result, not the photo.
        </li>
      </ul>

      <h2>How we use it</h2>
      <ul>
        <li>To take, deliver and support your orders, returns and refunds, and to print your invoices.</li>
        <li>To send order and account messages by email and in the app, and by WhatsApp only if you opt in.</li>
        <li>To personalise recommendations from your browsing and orders. You can ask us to switch this off.</li>
        <li>To send offers and news only if you have agreed to receive marketing messages.</li>
        <li>To keep the website secure and prevent misuse.</li>
      </ul>

      <h2>Who we share it with</h2>
      <ul>
        <li>Our delivery partners get the name, phone number and address needed to deliver your order.</li>
        <li>When online payment is used, the payment provider processes your payment details.</li>
        <li>Email and WhatsApp messages are sent through the providers we use for those channels.</li>
        <li>
          The address map loads map images from OpenStreetMap, which sees your device’s internet address. Voice search may
          use your browser’s own speech recognition service (for example Google’s in Chrome).
        </li>
        <li>We do not sell your personal information.</li>
      </ul>

      <h2>Information stored in your browser</h2>
      <p>
        The website keeps a few items in your browser’s local storage: your sign-in session, recently viewed products, your
        compare list, the PIN code you entered and your voice settings. Clearing your browser data removes them.
      </p>

      <h2>Your choices</h2>
      <ul>
        <li>Update your profile, addresses and notification preferences in your account.</li>
        <li>Clear your AI assistant, voice search and photo search history at any time.</li>
        <li>
          Contact us to change your marketing, WhatsApp or personalisation choices, or to deactivate your account.
        </li>
      </ul>
      <PendingDecision>
        Account deletion on request, how long each kind of information is kept, and the contact person for privacy
        complaints are being finalised. Until then, contact us about any request regarding your information.
      </PendingDecision>

      <h2>Security</h2>
      <p>
        Passwords are stored only as secure one-way hashes and are never shown to anyone, including us. Delivery photos are kept in private storage that is
        not publicly accessible.
      </p>
    </InfoPage>
  )
}

/** /policies/terms-of-service — the rules of buying on the website as the system applies them. */
export function TermsOfServicePage() {
  return (
    <InfoPage
      group="policies"
      title="Terms of Service"
      intro={`The terms for using the ${business.name} website and buying from us.`}
      note={<PolicyNote />}
    >
      <h2>About these terms</h2>
      <p>
        This website is run by {business.name}, {business.addressText}. By using the website or placing an order you agree to
        these terms and to our <Link to="/policies/refund-policy">Refund Policy</Link>,{' '}
        <Link to="/policies/shipping-policy">Shipping Policy</Link> and{' '}
        <Link to="/policies/privacy-policy">Privacy Policy</Link>.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>Give accurate details and keep your password private. You are responsible for orders placed from your account.</li>
      </ul>

      <h2>Products and prices</h2>
      <ul>
        <li>All prices are in Indian rupees and include GST. The MRP is shown for comparison.</li>
        <li>
          Prices, offers and stock can change. The price that applies is the one shown at checkout when you place the order.
        </li>
        <li>
          Bulk prices apply automatically for larger quantities. Automatic offers and one coupon per order can apply, under
          the conditions shown with each offer or coupon.
        </li>
        <li>
          Product details come from our catalogue and manufacturers. Check the specifications and compatibility before you
          order. Suggestions from the AI assistant and planning tools are guidance only.
        </li>
      </ul>

      <h2>Orders and payment</h2>
      <ul>
        <li>
          Cash on delivery orders are confirmed when placed. Online orders are confirmed once payment succeeds; unpaid online
          orders are cancelled after 30 minutes.
        </li>
        <li>
          Cash on delivery is available on eligible orders up to ₹10,000 and may depend on the store and area serving your
          address.
        </li>
        <li>
          Your invoice or receipt is available with each order and shows your GSTIN when you have added one.
        </li>
      </ul>

      <h2>Quotations</h2>
      <p>
        You can request a quotation from your cart. A quotation is valid until the date shown on it; once accepted, it is
        ordered at the quoted prices. Coupons can’t be combined with quoted prices.
      </p>

      <h2>Credits</h2>
      <p>
        Credits are store credit for use on our website. They can pay up to 20% of an order (not the delivery fee), expire
        90 days after they are earned, and can’t be exchanged for cash.
      </p>

      <h2>Delivery, cancellations and returns</h2>
      <p>
        These are covered by the <Link to="/policies/shipping-policy">Shipping Policy</Link> and the{' '}
        <Link to="/policies/refund-policy">Refund Policy</Link>.
      </p>

      <PendingDecision>
        The governing law and jurisdiction, limits of liability, and how pricing or listing errors are handled are being
        finalised.
      </PendingDecision>

      <h2>Contact</h2>
      <ContactLine />
    </InfoPage>
  )
}
