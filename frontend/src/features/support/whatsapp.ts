import { env } from '@/lib/env'

/** wa.me link with a prefilled question, or '' when the shop has no WhatsApp number configured. */
export function whatsappLink(productName: string, productUrl: string) {
  const number = env.supportWhatsApp.replace(/\D/g, '')
  if (!number) return ''
  const text = `Hi, I have a question about ${productName}: ${productUrl}`
  return `https://wa.me/${number}?text=${encodeURIComponent(text)}`
}
