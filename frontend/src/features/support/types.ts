/** Support conversations: product enquiries and WhatsApp attachments. */

export interface SupportProductRef {
  id: number
  name: string
  slug: string
}

/** A photo or document a customer sent on WhatsApp. The file stays with WhatsApp; staff open it
 * through `/support/messages/{message}/attachments/{index}/`. */
export interface SupportAttachment {
  type: 'image' | 'document'
  media_id: string
  mime_type: string
  caption: string
  sha256?: string
  filename?: string
}

export interface ProductEnquiryResult {
  id: number
  subject: string
  product: SupportProductRef | null
}
