import { useState } from 'react'

import { useAttachmentUrl } from './api'
import type { SupportAttachment } from './types'

const VIEWABLE = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']

function label(attachment: SupportAttachment) {
  if (attachment.filename) return attachment.filename
  return attachment.type === 'image' ? 'Photo' : 'Document'
}

function Attachment({ messageId, index, attachment }: { messageId: number; index: number; attachment: SupportAttachment }) {
  const viewable = VIEWABLE.includes(attachment.mime_type)
  const isImage = attachment.type === 'image' && viewable && attachment.mime_type !== 'application/pdf'
  // Photos load straight away (that's what staff need to see); documents only when asked.
  const [open, setOpen] = useState(isImage)
  const file = useAttachmentUrl(messageId, index, viewable && open)

  if (!viewable) {
    return (
      <p className="text-xs text-ink-600">
        {label(attachment)} ({attachment.mime_type || 'unknown type'}) — open it in WhatsApp Manager.
      </p>
    )
  }
  if (!open) {
    return (
      <button type="button" className="text-xs font-semibold underline" onClick={() => setOpen(true)}>
        Open {label(attachment)}
      </button>
    )
  }
  if (file.isPending) return <p className="text-xs text-ink-600">Loading {label(attachment).toLowerCase()}…</p>
  if (file.isError) {
    return (
      <p role="alert" className="text-xs text-danger-600">
        {label(attachment)} can’t be shown here (the messaging provider keeps it). Open it in WhatsApp Manager.
      </p>
    )
  }
  if (isImage) {
    return (
      <a href={file.data} target="_blank" rel="noreferrer" className="block">
        <img src={file.data} alt={attachment.caption || 'Photo sent by the customer'} className="max-h-64 rounded-md object-contain" />
      </a>
    )
  }
  return (
    <a href={file.data} target="_blank" rel="noreferrer" className="text-xs font-semibold underline">
      View {label(attachment)}
    </a>
  )
}

/** Photos and documents a customer sent on WhatsApp, for the staff support inbox. */
export function MessageAttachments({ messageId, attachments }: { messageId: number; attachments?: SupportAttachment[] }) {
  if (!attachments?.length) return null
  return (
    <ul className="mt-2 space-y-2" aria-label="Attachments">
      {attachments.map((attachment, index) => (
        <li key={`${attachment.media_id}-${index}`}>
          <Attachment messageId={messageId} index={index} attachment={attachment} />
        </li>
      ))}
    </ul>
  )
}
