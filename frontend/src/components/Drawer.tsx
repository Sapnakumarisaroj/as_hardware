import { useEffect, useRef, type ReactNode } from 'react'

import { CloseIcon } from './icons'

interface Props {
  open: boolean
  onClose: () => void
  title: string
  side?: 'left' | 'right'
  children: ReactNode
  footer?: ReactNode
}

/** Accessible slide-over panel (mobile filters, mobile menu). Escape or backdrop closes it. */
export function Drawer({ open, onClose, title, side = 'left', children, footer }: Props) {
  const panelRef = useRef<HTMLDivElement>(null)

  // The latest onClose, without re-running the effect below when the parent passes a new
  // function on every render (that would move the focus away from the field being typed in).
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    panelRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeRef.current()
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [open])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-ink-950/50" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={`absolute inset-y-0 ${side === 'left' ? 'left-0' : 'right-0'} flex w-[88vw] max-w-sm flex-col bg-white shadow-xl focus:outline-none`}
      >
        <div className="flex items-center justify-between border-b border-steel-200 px-4 py-3">
          <h2 className="text-base font-bold">{title}</h2>
          <button type="button" onClick={onClose} aria-label={`Close ${title.toLowerCase()}`} className="p-1">
            <CloseIcon className="size-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer && <div className="border-t border-steel-200 p-4">{footer}</div>}
      </div>
    </div>
  )
}
