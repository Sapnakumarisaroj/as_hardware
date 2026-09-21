import { useHealth } from './api'

/** Live API/database status from GET /api/health/. */
export function SystemStatus() {
  const { data, isPending, isError, error, refetch, isFetching } = useHealth()

  if (isPending) {
    return <StatusPill tone="neutral" label="Checking service status…" />
  }
  if (isError) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <StatusPill tone="bad" label="Service unreachable" />
        <span className="text-sm text-steel-200">{error.message}</span>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="rounded-md bg-amber-500 px-3 py-1.5 text-sm font-semibold text-ink-950 hover:bg-amber-600 disabled:opacity-50"
        >
          {isFetching ? 'Retrying…' : 'Retry'}
        </button>
      </div>
    )
  }
  const healthy = data.status === 'ok'
  return (
    <StatusPill
      tone={healthy ? 'good' : 'bad'}
      label={healthy ? `All systems operational · v${data.version}` : `Degraded: database ${data.database}`}
    />
  )
}

function StatusPill({ tone, label }: { tone: 'good' | 'bad' | 'neutral'; label: string }) {
  const dot = { good: 'bg-success-600', bad: 'bg-danger-600', neutral: 'bg-steel-400 animate-pulse' }[tone]
  return (
    <span
      role="status"
      className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-sm text-ink-900 shadow-sm ring-1 ring-steel-200"
    >
      <span aria-hidden className={`size-2 rounded-full ${dot}`} />
      {label}
    </span>
  )
}
