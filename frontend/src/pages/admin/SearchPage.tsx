import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'

import { ErrorState, PageSpinner } from '@/components/feedback'
import { useToast } from '@/components/toast'
import {
  useRebuildSearchIndex,
  useRefreshProductEmbedding,
  useSearchExplain,
  useSearchIndex,
} from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { SearchExplainRow, SearchIndexStatus } from '@/features/admin/types'
import {
  Badge,
  ConfirmDialog,
  DataTable,
  dateTime,
  errorMessage,
  Facts,
  NotAllowed,
  PageHeader,
  Panel,
  type Column,
} from '@/features/admin/ui'
import { usePageMeta } from '@/lib/usePageMeta'

const EMBEDDERS: Record<SearchIndexStatus['embedder']['kind'], string> = {
  none: 'Off (keyword search and related words only)',
  hashing: 'Built-in (typo-tolerant, no download)',
  sentence_transformers: 'Local AI model',
}

function IndexStatus({ status }: { status: SearchIndexStatus }) {
  const { embedder } = status
  const health = !embedder.available ? (
    <Badge tone="warn">Keyword search only</Badge>
  ) : status.missing || status.stale ? (
    <Badge tone="warn">Needs an update</Badge>
  ) : status.ready ? (
    <Badge tone="good">Up to date</Badge>
  ) : (
    <Badge tone="warn">Not built yet</Badge>
  )
  return (
    <Panel title="Index" action={health}>
      <Facts
        items={[
          ['Search', status.search_backend === 'hybrid' ? 'Keywords + meaning (hybrid)' : 'Keywords only'],
          ['Embedder', EMBEDDERS[embedder.kind] ?? embedder.kind],
          ...(embedder.model ? ([['Model', embedder.model]] as [string, string][]) : []),
          ['Products', status.products],
          ['Indexed', status.indexed],
          ['Missing', status.missing],
          ['Out of date', status.stale],
          ...(status.other_embedder
            ? ([['From another embedder', `${status.other_embedder} (replaced on rebuild)`]] as [string, string][])
            : []),
          ['Last updated', dateTime(status.last_updated)],
        ]}
      />
      {!embedder.available && (
        <p className="mt-3 text-sm text-ink-600">
          {embedder.kind === 'none'
            ? 'Semantic search is switched off (SEMANTIC_EMBEDDER=none). Customers still get keyword search with related words, Hindi/Hinglish and typo correction.'
            : 'The AI model isn’t available on this server right now. Customers get keyword search meanwhile; nothing is broken.'}
        </p>
      )}
    </Panel>
  )
}

function Rebuild({ status }: { status: SearchIndexStatus }) {
  const rebuild = useRebuildSearchIndex()
  const refresh = useRefreshProductEmbedding()
  const toast = useToast()
  const [asking, setAsking] = useState(false)
  const [productId, setProductId] = useState('')
  const off = !status.embedder.available

  const update = () =>
    rebuild.mutate(false, {
      onSuccess: ({ result }) =>
        toast.show(`Index updated: ${result.embedded} embedded, ${result.unchanged} unchanged, ${result.removed} removed.`),
      onError: (error) => toast.show(errorMessage(error)),
    })
  const refreshOne = (event: FormEvent) => {
    event.preventDefault()
    const id = Number(productId)
    if (!id) return
    refresh.mutate(id, {
      onSuccess: () => {
        toast.show(`Product ${id} re-indexed.`)
        setProductId('')
      },
      onError: (error) => toast.show(errorMessage(error)),
    })
  }

  return (
    <Panel title="Update">
      <p className="text-sm text-ink-600">
        Products are re-indexed automatically when they change. Use this after an import, or when products are
        missing or out of date. Only changed products are embedded again.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="btn-primary" disabled={off || rebuild.isPending} onClick={update}>
          {rebuild.isPending ? 'Updating…' : 'Update index'}
        </button>
        <button type="button" className="btn-secondary" disabled={off || rebuild.isPending} onClick={() => setAsking(true)}>
          Rebuild everything
        </button>
      </div>
      <form onSubmit={refreshOne} className="mt-4 flex items-end gap-2 border-t border-steel-100 pt-3">
        <div className="flex-1">
          <label htmlFor="embed-product" className="label">
            Re-index one product (ID)
          </label>
          <input
            id="embed-product"
            className="input"
            inputMode="numeric"
            value={productId}
            onChange={(e) => setProductId(e.target.value.replace(/\D/g, ''))}
          />
        </div>
        <button type="submit" className="btn-secondary" disabled={off || !productId || refresh.isPending}>
          Re-index
        </button>
      </form>
      <ConfirmDialog
        open={asking}
        title="Rebuild the whole search index?"
        confirmLabel="Rebuild"
        busy={rebuild.isPending}
        error={rebuild.error}
        onClose={() => {
          rebuild.reset()
          setAsking(false)
        }}
        onConfirm={() =>
          rebuild.mutate(true, {
            onSuccess: ({ result }) => {
              toast.show(`Rebuilt: ${result.embedded} products embedded.`)
              setAsking(false)
            },
          })
        }
      >
        <p>
          Every product is embedded again ({status.products} products). With a local AI model this can take a while on a
          large catalogue; search keeps working while it runs.
        </p>
      </ConfirmDialog>
    </Panel>
  )
}

const SOURCES: Record<string, string> = { keyword: 'Your words', related: 'Related words', semantic: 'Meaning' }

const COLUMNS: Column<SearchExplainRow>[] = [
  {
    header: 'Product',
    cell: (row) => (
      <>
        <Link to={`/admin/products/${row.product_id}`} className="font-semibold underline-offset-2 hover:underline">
          {row.name}
        </Link>
        {row.reason && <span className="block text-xs text-ink-600">{row.reason.text}</span>}
      </>
    ),
  },
  { header: 'Found by', cell: (row) => (row.reason ? SOURCES[row.reason.type] : 'Your words') },
  { header: 'Keyword', numeric: true, cell: (row) => row.keyword },
  { header: 'Related', numeric: true, cell: (row) => row.related },
  { header: 'Meaning', numeric: true, cell: (row) => (row.cosine === null ? '—' : row.cosine.toFixed(2)) },
  { header: 'Score', numeric: true, cell: (row) => <strong>{row.final}</strong> },
]

function Explain() {
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const explained = useSearchExplain(query)
  const data = explained.data

  return (
    <Panel title="Try a search">
      <form
        className="flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setQuery(draft.trim())
        }}
      >
        <div className="flex-1">
          <label htmlFor="explain-q" className="label">
            What a customer might type
          </label>
          <input
            id="explain-q"
            className="input"
            placeholder="e.g. diwar me hole karne ka saman"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </div>
        <button type="submit" className="btn-primary" disabled={!draft.trim()}>
          Explain
        </button>
      </form>
      {explained.isFetching && !data && <p className="mt-3 text-sm text-ink-600">Searching…</p>}
      {explained.isError && <p className="mt-3 text-sm text-danger-600">{errorMessage(explained.error)}</p>}
      {data && (
        <div className="mt-4 space-y-3">
          <p className="text-sm text-ink-600">
            {data.mode === 'hybrid' ? 'Keywords + meaning' : 'Keywords only'}
            {data.related_terms.length > 0 && <> · understood as: {data.related_terms.join(', ')}</>}
          </p>
          {data.results.length === 0 ? (
            <p className="text-sm">No products match. Customers see an empty result, never made-up products.</p>
          ) : (
            <DataTable caption="Ranking" columns={COLUMNS} rows={data.results.slice(0, 20)} rowKey={(row) => row.product_id} />
          )}
        </div>
      )}
    </Panel>
  )
}

function Search() {
  const status = useSearchIndex()
  if (status.isPending) return <PageSpinner label="Loading the search index…" />
  if (status.isError) return <ErrorState error={status.error} onRetry={() => void status.refetch()} title="Couldn’t load the search index" />
  return (
    <>
      <PageHeader
        title="Search"
        description="How customer searches are understood: keywords, related words (English, Hindi, Hinglish, typos) and meaning."
      />
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5">
          <IndexStatus status={status.data} />
          <Rebuild status={status.data} />
        </div>
        <div className="lg:col-span-2">
          <Explain />
        </div>
      </div>
    </>
  )
}

export function AdminSearchPage() {
  usePageMeta('Search')
  const session = useSession()
  return session.is_admin ? <Search /> : <NotAllowed what="The search index" />
}
