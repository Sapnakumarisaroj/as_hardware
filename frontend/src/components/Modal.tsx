import { useEffect, useId, useRef, type ReactNode } from 'react'

import { CloseIcon } from './icons'

interface Props {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
}

/** Accessible dialog: a bottom sheet on phones, a centred panel on larger screens. Escape/backdrop close it. */
export function Modal({ open, onClose, title, children, footer }: Props) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    panelRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-ink-950/50" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative flex max-h-[92vh] w-full flex-col rounded-t-xl bg-white shadow-xl focus:outline-none sm:max-w-lg sm:rounded-xl"
      >
        <div className="flex items-center justify-between border-b border-steel-200 px-5 py-3">
          <h2 id={titleId} className="text-base font-bold">
            {title}
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="-mr-2 p-2">
            <CloseIcon className="size-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="border-t border-steel-200 px-5 py-3">{footer}</div>}
      </div>
    </div>
  )
}
