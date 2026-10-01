import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { ErrorState, Spinner } from '@/components/feedback'
import { CameraIcon, ImageIcon, TrashIcon } from '@/components/icons'
import { RecommendationCard } from '@/features/ai/components'
import { useAuth } from '@/features/auth/context'
import {
  useDeleteImageSearch,
  useImageSearch,
  useImageSearchHistory,
  useImageSearchStatus,
  useSavedImageSearch,
} from '@/features/imageSearch/api'
import { ACCEPTED_TYPES, problemWith, shrink } from '@/features/imageSearch/prepare'
import type { ImageSearchHistoryRow, ImageSearchResult } from '@/features/imageSearch/types'
import { ApiError } from '@/lib/api/errors'
import { formatDate } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const DEFAULT_MAX_BYTES = 8 * 1024 * 1024

const HEADINGS: Record<ImageSearchResult['status'], (r: ImageSearchResult) => string> = {
  identified: (r) => `Looks like: ${r.identification?.label ?? 'a hardware item'}`,
  uncertain: () => 'We’re not sure what this is',
  not_hardware: () => 'This doesn’t look like a hardware item',
  no_match: (r) => `${capitalise(r.identification?.label ?? 'This item')} isn’t in our catalogue`,
  unavailable: () => 'Photo search isn’t available right now',
}

function capitalise(text: string) {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function Confidence({ result }: { result: ImageSearchResult }) {
  const found = result.identification
  if (!found || result.status === 'no_match') return null
  const tone =
    found.level === 'high' ? 'bg-success-600/10 text-success-600' : found.level === 'medium' ? 'bg-amber-100 text-ink-900' : 'bg-steel-100 text-ink-800'
  const words = found.calibrated
    ? `${found.level === 'high' ? 'Very likely' : found.level === 'medium' ? 'Likely' : 'Unsure'} · ${found.percent}%`
    : `AI estimate · ${found.percent}%`
  return (
    <div className="flex items-center gap-3">
      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${tone}`} data-testid="confidence">
        {words}
      </span>
      <div
        className="h-2 w-32 overflow-hidden rounded-full bg-steel-100"
        role="meter"
        aria-label="Confidence"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={found.percent}
      >
        <div className={`h-full ${found.level === 'low' ? 'bg-steel-400' : 'bg-amber-500'}`} style={{ width: `${found.percent}%` }} />
      </div>
    </div>
  )
}

function TextSearch({ initial = '' }: { initial?: string }) {
  const navigate = useNavigate()
  const [text, setText] = useState(initial)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (text.trim()) void navigate(`/search?q=${encodeURIComponent(text.trim())}`)
  }
  return (
    <form onSubmit={submit} className="flex gap-2" role="search" aria-label="Search in words">
      <label htmlFor="describe-item" className="sr-only">
        Describe the item
      </label>
      <input
        id="describe-item"
        className="input flex-1"
        placeholder="e.g. tap for the bathroom sink"
        value={text}
        maxLength={100}
        onChange={(e) => setText(e.target.value)}
      />
      <button type="submit" className="btn-primary" disabled={!text.trim()}>
        Search
      </button>
    </form>
  )
}

export function ImageSearchResultView({ result }: { result: ImageSearchResult }) {
  const sure = result.status === 'identified'
  return (
    <section aria-labelledby="image-result-heading" className="space-y-4">
      <div className="space-y-2 rounded-lg bg-white p-4 ring-1 ring-steel-200">
        <h2 id="image-result-heading" className="text-lg font-bold">
          {HEADINGS[result.status](result)}
        </h2>
        <Confidence result={result} />
        <p className="text-sm text-ink-800">{result.explanation}</p>
        {result.identification?.description && <p className="text-sm text-ink-600">{result.identification.description}</p>}
        {result.notice && (
          <p className="rounded-md bg-amber-100 px-3 py-2 text-sm text-ink-900" role="note">
            {result.notice}
          </p>
        )}
        {result.alternatives.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-ink-600">{sure ? 'Could also be:' : 'Other possibilities:'}</span>
            {result.alternatives.map((alt) => (
              <Link
                key={alt.label}
                to={`/search?q=${encodeURIComponent(alt.search)}`}
                className="rounded-full bg-steel-100 px-2.5 py-0.5 hover:bg-steel-200"
              >
                {alt.label} ({alt.percent}%)
              </Link>
            ))}
          </div>
        )}
        {result.search_query && result.status !== 'not_hardware' && (
          <p className="text-sm">
            <Link to={`/search?q=${encodeURIComponent(result.search_query)}`} className="font-semibold text-amber-600 hover:underline">
              Search the shop for “{result.search_query}”
            </Link>
          </p>
        )}
        {(result.status === 'unavailable' || result.status === 'no_match' || result.status === 'not_hardware') && (
          <div className="pt-1">
            <p className="mb-2 text-sm text-ink-600">Or describe what you need in words:</p>
            <TextSearch />
          </div>
        )}
      </div>

      {result.products.length > 0 && (
        <div>
          <h2 className="mb-2 text-base font-bold">{sure ? 'Matching products' : 'Possible matches'}</h2>
          {!sure && <p className="mb-2 text-sm text-ink-600">Check the details before you buy: we couldn’t be sure from the photo.</p>}
          <ul className="grid gap-3 sm:grid-cols-2" aria-label={sure ? 'Matching products' : 'Possible matches'}>
            {result.products.map((product) => (
              <RecommendationCard key={product.id} product={product} />
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function Uploader({ maxBytes, busy, onFile }: { maxBytes: number; busy: boolean; onFile: (file: File) => void }) {
  const cameraRef = useRef<HTMLInputElement>(null)
  const pickRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const accept = ACCEPTED_TYPES.join(',')

  const take = (files: FileList | null) => {
    const file = files?.[0]
    if (file) onFile(file)
  }
  const drop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    take(event.dataTransfer.files)
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
      className={`flex flex-col items-center gap-3 rounded-lg border-2 border-dashed p-6 text-center ${dragging ? 'border-amber-500 bg-amber-100' : 'border-steel-200 bg-white'}`}
    >
      <ImageIcon className="size-10 text-steel-400" />
      <p className="text-sm text-ink-800">
        Photograph one item on its own, in good light. We’ll find it in our catalogue.
      </p>
      <div className="flex flex-wrap justify-center gap-2">
        <button type="button" className="btn-primary inline-flex items-center gap-2" disabled={busy} onClick={() => cameraRef.current?.click()}>
          <CameraIcon className="size-4" />
          Take a photo
        </button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={() => pickRef.current?.click()}>
          Choose a photo
        </button>
      </div>
      <p className="text-xs text-ink-600">
        JPEG, PNG or WebP, up to {Math.round(maxBytes / (1024 * 1024))} MB. You can also drop a photo here. Photos are not stored.
      </p>
      {/* capture opens the rear camera on phones; desktops fall back to choosing a file */}
      <input
        ref={cameraRef}
        type="file"
        accept={accept}
        capture="environment"
        className="sr-only"
        tabIndex={-1}
        aria-label="Take a photo"
        onChange={(e) => {
          take(e.target.files)
          e.target.value = ''
        }}
      />
      <input
        ref={pickRef}
        type="file"
        accept={accept}
        className="sr-only"
        tabIndex={-1}
        aria-label="Choose a photo"
        onChange={(e) => {
          take(e.target.files)
          e.target.value = ''
        }}
      />
    </div>
  )
}

function History({ rows, onOpen }: { rows: ImageSearchHistoryRow[]; onOpen: (id: number) => void }) {
  const remove = useDeleteImageSearch()
  if (rows.length === 0) return null
  return (
    <section aria-labelledby="image-history-heading" className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
      <div className="mb-2 flex items-center justify-between">
        <h2 id="image-history-heading" className="text-base font-bold">
          Your recent photo searches
        </h2>
        <button type="button" className="text-sm text-danger-600 hover:underline" disabled={remove.isPending} onClick={() => remove.mutate('all')}>
          Clear all
        </button>
      </div>
      <ul className="divide-y divide-steel-100 text-sm">
        {rows.map((row) => (
          <li key={row.id} className="flex items-center justify-between gap-2 py-2">
            <button type="button" className="min-w-0 flex-1 text-left hover:text-amber-600" onClick={() => onOpen(row.id)}>
              <span className="block truncate font-semibold">{row.label ? capitalise(row.label) : row.title}</span>
              <span className="block text-xs text-ink-600">
                {formatDate(row.created_at)}
                {row.percent !== null && ` · ${row.percent}%`}
                {` · ${row.product_count} ${row.product_count === 1 ? 'product' : 'products'}`}
              </span>
            </button>
            <button
              type="button"
              className="p-1 text-ink-600 hover:text-danger-600"
              aria-label={`Delete photo search ${row.label || row.title}`}
              disabled={remove.isPending}
              onClick={() => remove.mutate(row.id)}
            >
              <TrashIcon className="size-4" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function ImageSearchPage() {
  usePageMeta('Search by photo', 'Take or upload a photo of a hardware item and find it in the catalogue.')
  const { status: authStatus } = useAuth()
  const status = useImageSearchStatus()
  const search = useImageSearch()
  const history = useImageSearchHistory()
  const [params, setParams] = useSearchParams()
  const savedId = params.get('id') ? Number(params.get('id')) : null
  const saved = useSavedImageSearch(search.data ? null : savedId)
  const [problem, setProblem] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  const maxBytes = status.data?.max_bytes ?? DEFAULT_MAX_BYTES
  const result = search.data ?? (savedId !== null ? saved.data : undefined)

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview)
  }, [preview])

  useEffect(() => {
    if (search.data) resultRef.current?.focus()
  }, [search.data])

  async function handleFile(file: File) {
    search.reset()
    const issue = problemWith(file, Math.max(maxBytes, 20 * 1024 * 1024)) // big phone photos are shrunk first
    if (issue) {
      setProblem(issue)
      return
    }
    const ready = await shrink(file)
    const tooBig = problemWith(ready, maxBytes)
    if (tooBig) {
      setProblem(tooBig)
      return
    }
    setProblem(null)
    try {
      setPreview(URL.createObjectURL(ready)) // only a preview: never let it stop the search
    } catch {
      setPreview(null)
    }
    if (savedId !== null) setParams({}, { replace: true })
    search.mutate(ready)
  }

  const serverError = search.error instanceof ApiError ? search.error.message : search.error ? 'Something went wrong. Please try again.' : null
  const off = status.data && !status.data.enabled

  return (
    <div className="container-page max-w-4xl space-y-5 py-6">
      <div>
        <h1 className="text-2xl font-extrabold">Search by photo</h1>
        <p className="text-sm text-ink-600">Not sure what it’s called? Show us. We only ever show products we really sell.</p>
      </div>

      {status.isError && <ErrorState error={status.error} onRetry={() => void status.refetch()} title="Couldn’t open photo search" />}

      {off ? (
        <div className="space-y-3 rounded-lg bg-white p-4 ring-1 ring-steel-200">
          <h2 className="text-base font-bold">Photo search isn’t switched on in this shop yet</h2>
          <p className="text-sm text-ink-600">Describe what you need instead, or ask our assistant.</p>
          <TextSearch />
          <Link to="/ai-assistant" className="text-sm font-semibold text-amber-600 hover:underline">
            Ask the hardware assistant
          </Link>
        </div>
      ) : (
        <>
          {status.data && !status.data.available && (
            <p className="rounded-md bg-amber-100 px-3 py-2 text-sm text-ink-900" role="status">
              Photo recognition is starting up or temporarily unavailable. You can still try; if it doesn’t work, search in words.
            </p>
          )}
          <Uploader maxBytes={maxBytes} busy={search.isPending} onFile={(file) => void handleFile(file)} />
        </>
      )}

      {problem && (
        <p className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600" role="alert">
          {problem}
        </p>
      )}
      {serverError && (
        <p className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600" role="alert">
          {serverError}
        </p>
      )}

      {(preview || search.isPending) && (
        <div className="flex items-center gap-4">
          {preview && <img src={preview} alt="Your photo" className="size-24 rounded-md object-cover ring-1 ring-steel-200" />}
          {search.isPending && <Spinner label="Looking at your photo…" />}
        </div>
      )}

      <div ref={resultRef} tabIndex={-1} className="outline-none">
        {result && <ImageSearchResultView result={result} />}
        {!result && savedId !== null && saved.isPending && <Spinner label="Loading the search…" />}
      </div>

      {authStatus === 'authenticated' ? (
        <History
          rows={history.data?.results ?? []}
          onOpen={(id) => {
            search.reset()
            setPreview(null)
            setParams({ id: String(id) })
          }}
        />
      ) : (
        <p className="text-xs text-ink-600">
          <Link to="/login?next=%2Fimage-search" className="font-semibold text-amber-600 hover:underline">
            Sign in
          </Link>{' '}
          to keep a history of your photo searches.
        </p>
      )}
    </div>
  )
}
