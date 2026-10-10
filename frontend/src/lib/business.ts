import { env } from './env'

/**
 * The shop's official details in one place: header, footer, contact page, login pages and page titles
 * read them from here. Name, phone, email and WhatsApp can be overridden with VITE_* variables
 * (see lib/env.ts); a blank WhatsApp number hides every WhatsApp link.
 */
const ADDRESS_LINES = ['264, 2nd Cross Road', 'Pete Krishnappa Layout, Kalkere', 'Bengaluru, Karnataka 560013'] as const
const COUNTRY = 'India'
const addressText = `${ADDRESS_LINES.join(', ')}, ${COUNTRY}`
const whatsappNumber = env.supportWhatsApp.replace(/\D/g, '')

export const business = {
  name: env.appName,
  /** For tight spots (the header next to the round logo). */
  shortName: 'AS Hardware',
  tagline: 'Complete Interior Hardware Solutions',
  addressLines: ADDRESS_LINES,
  country: COUNTRY,
  addressText,
  phone: env.supportPhone,
  phoneHref: env.supportPhone ? `tel:${env.supportPhone.replace(/[^\d+]/g, '')}` : '',
  email: env.supportEmail,
  emailHref: env.supportEmail ? `mailto:${env.supportEmail}` : '',
  whatsapp: env.supportWhatsApp,
  whatsappHref: whatsappNumber ? `https://wa.me/${whatsappNumber}` : '',
  /** Google Maps directions to the shop, searched by its address (no pinned coordinates are known). */
  directionsUrl: `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(addressText)}`,
  hours: env.storeHours,
  logo: {
    /** Round "AS" mark on white, for the header, menus and small spaces. */
    mark: '/images/as-hardware-logo-mark.png',
    /** The full official logo (720 × 453), for the footer and contact page. */
    full: '/images/as-hardware-logo-full.png',
    fullWidth: 720,
    fullHeight: 453,
  },
} as const
