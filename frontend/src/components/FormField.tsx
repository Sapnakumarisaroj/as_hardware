import type { InputHTMLAttributes } from 'react'

/** Labelled input with an accessible inline error message. */
export function FormField({
  id,
  label,
  error,
  hint,
  className = '',
  ...input
}: { id: string; label: string; error?: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  const describedBy = [error && `${id}-error`, hint && `${id}-hint`].filter(Boolean).join(' ') || undefined
  return (
    <div className={className}>
      <label htmlFor={id} className="label">
        {label}
        {input.required && <span className="text-danger-600"> *</span>}
      </label>
      <input id={id} name={id} className="input" aria-invalid={Boolean(error)} aria-describedby={describedBy} {...input} />
      {hint && !error && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-ink-600">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-danger-600">
          {error}
        </p>
      )}
    </div>
  )
}
