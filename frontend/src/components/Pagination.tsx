interface Props {
  page: number
  pageSize: number
  total: number
  onChange: (page: number) => void
}

/** Numbered pagination for backend-paginated lists (the browser never loads everything). */
export function Pagination({ page, pageSize, total, onChange }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  const nearby = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages))
  const sorted = [...nearby].sort((a, b) => a - b)

  const cell = 'grid h-9 min-w-9 place-items-center rounded-md px-2 text-sm font-medium'
  return (
    <nav aria-label="Pagination" className="mt-8 flex items-center justify-center gap-1">
      <button
        type="button"
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        className="btn-secondary h-9 px-3 py-0"
      >
        Previous
      </button>
      {sorted.map((p, i) => (
        <span key={p} className="flex items-center gap-1">
          {i > 0 && p - (sorted[i - 1] ?? p) > 1 && <span className="px-1 text-ink-600">…</span>}
          <button
            type="button"
            onClick={() => onChange(p)}
            aria-current={p === page ? 'page' : undefined}
            aria-label={`Page ${p}`}
            className={`${cell} ${p === page ? 'bg-ink-900 text-white' : 'bg-white text-ink-900 ring-1 ring-steel-200 hover:bg-steel-50'}`}
          >
            {p}
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={() => onChange(page + 1)}
        disabled={page >= pages}
        className="btn-secondary h-9 px-3 py-0"
      >
        Next
      </button>
    </nav>
  )
}
