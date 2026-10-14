import { env } from './env'

/**
 * The shop's official details in one place: header, footer, contact page, login pages and page titles
 * read them from here. Name, phone, email and WhatsApp can be overridden with VITE_* variables
 * (see lib/env.ts); a blank WhatsApp number hides every WhatsApp link.
 */
const ADDRESS_LINES = ['264, 2nd Cross Road', 'Pete Krishnappa Layout, Kalkere', 'Bengaluru, Karnataka 560113'] as const
const COUNTRY = 'India'
const addressText = `${ADDRESS_LINES.join(', ')}, ${COUNTRY}`
const whatsappNumber = env.supportWhatsApp.replace(/\D/g, '')
const telHref = (phone: string) => `tel:${phone.replace(/[^\d+]/g, '')}`
/** Every shop number, main first (VITE_SUPPORT_PHONE), each with its own tap-to-call link. */
const PHONES = [...new Set([env.supportPhone, '6361462556'].filter(Boolean))].map((number) => ({ number, href: telHref(number) }))

export const business = {
  name: env.appName,
  /** For tight spots (the header next to the round logo). */
  shortName: 'AS Hardware',
  tagline: 'One Stop for All Interior Solutions',
  /** Shown under the AS symbol in the logo lock-up. */
  nameUnderSymbol: 'Hardware and Plywood',
  addressLines: ADDRESS_LINES,
  country: COUNTRY,
  addressText,
  phone: env.supportPhone,
  phoneHref: env.supportPhone ? telHref(env.supportPhone) : '',
  phones: PHONES,
  email: env.supportEmail,
  emailHref: env.supportEmail ? `mailto:${env.supportEmail}` : '',
  whatsapp: env.supportWhatsApp,
  whatsappHref: whatsappNumber ? `https://wa.me/${whatsappNumber}` : '',
  /** Google Maps directions to the shop, searched by its address (no pinned coordinates are known). */
  directionsUrl: `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(addressText)}`,
  logo: {
    /** The AS symbol cropped from the official logo (logo_1.png): navbar, menus, sign-in pages. */
    symbol: '/images/as-hardware-logo-symbol.png',
    symbolWidth: 421,
    symbolHeight: 360,
    /** The same logo, larger, for the Contact page. */
    full: '/images/as-hardware-logo-full.png',
    fullWidth: 1200,
    fullHeight: 800,
  },
} as const
