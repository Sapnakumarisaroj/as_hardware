import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

type Tone = 'success' | 'error' | 'info'

interface Toast {
  id: number
  tone: Tone
  message: string
  action?: { label: string; to: string }
}

interface ToastApi {
  show: (message: string, options?: { tone?: Tone; action?: Toast['action'] }) => void
}

const ToastContext = createContext<ToastApi | null>(null)

/** Lightweight, accessible toasts (announced through an aria-live region). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), [])

  const show = useCallback<ToastApi['show']>(
    (message, options) => {
      const id = nextId.current++
      setToasts((all) => [...all.slice(-2), { id, message, tone: options?.tone ?? 'success', action: options?.action }])
      window.setTimeout(() => dismiss(id), 4500)
    },
    [dismiss],
  )

  const value = useMemo(() => ({ show }), [show])
  const tones: Record<Tone, string> = {
    success: 'border-success-600',
    error: 'border-danger-600',
    info: 'border-amber-500',
  }

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 sm:bottom-6"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.tone === 'error' ? 'alert' : 'status'}
            className={`pointer-events-auto flex w-full max-w-md items-center gap-3 rounded-lg border-l-4 bg-ink-900 px-4 py-3 text-sm text-white shadow-lg ${tones[toast.tone]}`}
          >
            <span className="flex-1">{toast.message}</span>
            {toast.action && (
              <Link to={toast.action.to} className="font-semibold text-amber-500 underline-offset-2 hover:underline">
                {toast.action.label}
              </Link>
            )}
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="text-steel-400 hover:text-white"
              aria-label="Dismiss notification"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
