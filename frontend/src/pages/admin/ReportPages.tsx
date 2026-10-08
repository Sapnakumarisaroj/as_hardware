import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'

import { ErrorState, PageSpinner, Spinner } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { useSession } from '@/features/admin/session'
import { Badge, DataTable, errorMessage, PageHeader, Panel, StatCard, Tabs, useListParams, type Column } from '@/features/admin/ui'
import {
  downloadReport,
  formatValue,
  useAsk,
  useAssistantHistory,
  useAssistantStatus,
  useReport,
  useReportList,
  type AssistantAnswer,
  type Kpi,
  type ReportParams,
  type ReportTable,
} from '@/features/analytics/api'
import { usePageMeta } from '@/lib/usePageMeta'

type Charts = typeof import('@/features/admin/charts')
let chartModule: Charts | null = null

/** The chart library, loaded the first time a chart is shown (same approach as the analytics page). */
function useCharts(): Charts | null {
  const [charts, setCharts] = useState(chartModule)
  useEffect(() => {
    if (charts) return
    let active = true
    void import('@/features/admin/charts').then((module) => {
      chartModule = module
      if (active) setCharts(module)
    })
    return () => {
      active = false
    }
  }, [charts])
  return charts
}

function Chart({ children }: { children: (charts: Charts) => ReactNode }) {
  const charts = useCharts()
  if (!charts) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner label="Loading chart…" />
      </div>
    )
  }
  return <>{children(charts)}</>
}

// --- Dates -------------------------------------------------------------------------------------------

function isoDay(date: Date): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(date) // YYYY-MM-DD
}

function today(): Date {
  return new Date(`${isoDay(new Date())}T12:00:00`)
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date)
  copy.setDate(copy.getDate() + days)
  return copy
}

const RANGES: [string, string][] = [
  ['today', 'Today'],
  ['7', 'Last 7 days'],
  ['30', 'Last 30 days'],
  ['90', 'Last 90 days'],
  ['this_month', 'This month'],
  ['last_month', 'Last month'],
  ['365', 'Last 12 months'],
  ['custom', 'Custom dates'],
]

function rangeDates(range: string): { from: string; to: string } {
  const now = today()
  if (range === 'today') return { from: isoDay(now), to: isoDay(now) }
  if (range === 'this_month') return { from: isoDay(new Date(now.getFullYear(), now.getMonth(), 1, 12)), to: isoDay(now) }
  if (range === 'last_month') {
    const first = new Date(now.getFullYear(), now.getMonth() - 1, 1, 12)
    const last = new Date(now.getFullYear(), now.getMonth(), 0, 12)
    return { from: isoDay(first), to: isoDay(last) }
  }
  const days = Number(range) || 30
  return { from: isoDay(addDays(now, -(days - 1))), to: isoDay(now) }
}

// --- Pieces ------------------------------------------------------------------------------------------

function KpiGrid({ kpis }: { kpis: Kpi[] }) {
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {kpis.map((k) => (
        <StatCard key={k.key} label={k.label} value={formatValue(k.value, k.format)} hint={k.hint} />
      ))}
    </dl>
  )
}

function BarList({ table }: { table: ReportTable }) {
  const chart = table.chart!
  const values = table.rows.slice(0, 10).map((row) => Number(row[chart.value] ?? 0))
  const top = Math.max(...values, 1)
  const format = table.columns.find((c) => c.key === chart.value)?.format ?? 'number'
  return (
    <ol className="space-y-2.5 text-sm" aria-label={`${table.title} chart`}>
      {table.rows.slice(0, 10).map((row, index) => (
        <li key={`${row[chart.label]}-${index}`}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-medium">{String(row[chart.label] ?? '—')}</span>
            <span className="font-semibold tabular-nums">{formatValue(row[chart.value], format)}</span>
          </div>
          <div aria-hidden className="mt-1 h-1.5 rounded-full bg-steel-100">
            <div className="h-full rounded-full bg-amber-500" style={{ width: `${Math.max((values[index]! / top) * 100, 1)}%` }} />
          </div>
        </li>
      ))}
    </ol>
  )
}

function ReportTableView({ table, onDownload }: { table: ReportTable; onDownload?: () => void }) {
  const columns: Column<Record<string, string | number | null>>[] = table.columns.map((c) => ({
    header: c.label,
    numeric: ['money', 'count', 'percent', 'minutes', 'number'].includes(c.format),
    cell: (row) => formatValue(row[c.key], c.format),
  }))
  const hasData = table.rows.length > 0 && table.chart && table.rows.some((row) => Number(row[table.chart!.value] ?? 0) > 0)
  return (
    <Panel
      title={table.title}
      action={
        onDownload && table.rows.length > 0 ? (
          <button type="button" className="btn-secondary" onClick={onDownload}>
            Download CSV<span className="sr-only">: {table.title}</span>
          </button>
        ) : undefined
      }
    >
      {table.rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-600">Nothing in this period.</p>
      ) : (
        <>
          {hasData && table.chart?.type === 'share' && (
            <Chart>
              {(charts) => (
                <charts.ShareChart
                  rows={table.rows.slice(0, 8).map((row) => ({ name: String(row[table.chart!.label]), value: Number(row[table.chart!.value] ?? 0) }))}
                />
              )}
            </Chart>
          )}
          {hasData && table.chart?.type === 'bar' && (
            <div className="mb-4">
              <BarList table={table} />
            </div>
          )}
          <DataTable caption={table.title} columns={columns} rows={table.rows} rowKey={(row) => JSON.stringify(row)} />
        </>
      )}
    </Panel>
  )
}

function StoreSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const session = useSession()
  if (session.stores.length < 2) return null
  return (
    <div>
      <label htmlFor="report-store" className="sr-only">
        Store
      </label>
      <select id="report-store" className="input w-auto" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{session.is_admin ? 'All stores' : 'All my stores'}</option>
        {session.stores.map((store) => (
          <option key={store.id} value={String(store.id)}>
            {store.name}
          </option>
        ))}
      </select>
    </div>
  )
}

// --- Reports page ------------------------------------------------------------------------------------

/** /admin/reports — every business report with date ranges, store filter, charts and CSV downloads. */
export function AdminReportsPage() {
  usePageMeta('Reports')
  const list = useListParams()
  const toast = useToast()
  const reportsList = useReportList()
  const key = list.get('report') || 'sales'
  const explicit = Boolean(list.get('from') && list.get('to'))
  const range = list.get('range') || (explicit ? 'custom' : '30')
  const dates = range === 'custom' ? { from: list.get('from'), to: list.get('to') } : rangeDates(range)
  const params: ReportParams = { ...dates, store: list.get('store'), group_by: list.get('group_by') }
  const report = useReport(key, params)

  const download = (table: string) =>
    void downloadReport(key, table, params).catch((error: unknown) => toast.show(errorMessage(error, 'The download didn’t work.')))

  const filters = (
    <>
      <StoreSelect value={list.get('store')} onChange={(store) => list.set({ store })} />
      <div>
        <label htmlFor="report-range" className="sr-only">
          Period
        </label>
        <select
          id="report-range"
          className="input w-auto"
          value={range}
          onChange={(e) => {
            const value = e.target.value
            if (value === 'custom') list.set({ range: value, ...rangeDates('30'), group_by: '' })
            else list.set({ range: value, from: '', to: '', group_by: '' })
          }}
        >
          {RANGES.map(([value, name]) => (
            <option key={value} value={value}>
              {name}
            </option>
          ))}
        </select>
      </div>
      {range === 'custom' && (
        <>
          <div>
            <label htmlFor="report-from" className="sr-only">
              From
            </label>
            <input id="report-from" type="date" className="input w-auto" value={list.get('from')} onChange={(e) => list.set({ range, from: e.target.value, to: list.get('to') })} />
          </div>
          <div>
            <label htmlFor="report-to" className="sr-only">
              To
            </label>
            <input id="report-to" type="date" className="input w-auto" value={list.get('to')} onChange={(e) => list.set({ range, from: list.get('from'), to: e.target.value })} />
          </div>
        </>
      )}
    </>
  )

  const tabs: [string, string][] = (reportsList.data ?? []).map((r) => [r.key, r.title])

  return (
    <div aria-busy={report.isFetching}>
      <PageHeader
        title="Reports"
        description="Read straight from your orders, stock and deliveries. Download any table as CSV for a spreadsheet."
        actions={filters}
      />
      {tabs.length > 0 && (
        <Tabs label="Reports" tabs={tabs} current={key} onChange={(value) => list.set({ report: value, range, ...(range === 'custom' ? dates : {}) })} />
      )}
      {report.isPending ? (
        <PageSpinner label="Adding up the numbers…" />
      ) : report.isError ? (
        <ErrorState error={report.error} onRetry={() => void report.refetch()} title="Couldn’t load the report" />
      ) : (
        <ReportBody
          data={report.data}
          onDownload={download}
          onGroupBy={(group_by) => list.set({ group_by, range, ...(range === 'custom' ? dates : {}) })}
        />
      )}
    </div>
  )
}

function ReportBody({
  data,
  onDownload,
  onGroupBy,
}: {
  data: NonNullable<ReturnType<typeof useReport>['data']>
  onDownload: (table: string) => void
  onGroupBy: (value: string) => void
}) {
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-ink-600">
          <span className="font-semibold text-ink-900">{data.title}</span> · {data.period.from} to {data.period.to} · {data.description}
        </p>
        <button type="button" className="btn-secondary" onClick={() => onDownload('kpis')}>
          Download summary CSV
        </button>
      </div>
      <KpiGrid kpis={data.kpis} />
      {data.series && data.series.some((row) => row.orders > 0) && (
        <Panel
          title={data.key === 'orders' ? 'Orders over time' : 'Revenue over time'}
          className="mt-5"
          action={
            <select aria-label="Group by" className="input w-auto" value={data.period.group_by} onChange={(e) => onGroupBy(e.target.value)}>
              <option value="day">By day</option>
              <option value="week">By week</option>
              <option value="month">By month</option>
            </select>
          }
        >
          <Chart>{(charts) => (data.key === 'orders' ? <charts.OrdersChart rows={data.series!} /> : <charts.RevenueChart rows={data.series!} />)}</Chart>
        </Panel>
      )}
      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        {data.tables.map((table) => (
          <ReportTableView key={table.key} table={table} onDownload={() => onDownload(table.key)} />
        ))}
      </div>
      {data.notes.length > 0 && (
        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-ink-600" aria-label="Notes">
          {data.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </>
  )
}

// --- Business assistant ------------------------------------------------------------------------------

function AnswerCard({ answer }: { answer: AssistantAnswer }) {
  return (
    <article className="rounded-lg bg-white p-4 ring-1 ring-steel-200" data-testid="answer">
      <p className="text-sm font-semibold text-ink-600">{answer.question}</p>
      <p className="mt-2 text-base text-ink-950">{answer.text}</p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {answer.period && <Badge>{answer.period.label}</Badge>}
        {answer.store && <Badge>{answer.store}</Badge>}
        <Badge tone={answer.source === 'ai' ? 'info' : 'neutral'}>{answer.source === 'ai' ? 'Worded by AI from the numbers' : 'From the numbers'}</Badge>
      </div>
      {answer.kpis && answer.kpis.length > 0 && (
        <div className="mt-3">
          <KpiGrid kpis={answer.kpis} />
        </div>
      )}
      {answer.comparison && (
        <p className="mt-3 text-sm" data-testid="comparison">
          {answer.comparison.label}: {formatValue(answer.comparison.current, answer.comparison.format)} vs{' '}
          {formatValue(answer.comparison.previous, answer.comparison.format)} ({answer.comparison.previous_period.from} to{' '}
          {answer.comparison.previous_period.to})
          {answer.comparison.change_percent !== null && (
            <strong className={answer.comparison.change_percent >= 0 ? ' text-success-600' : ' text-danger-600'}>
              {' '}
              {answer.comparison.change_percent >= 0 ? '+' : ''}
              {answer.comparison.change_percent}%
            </strong>
          )}
        </p>
      )}
      {answer.table && (
        <div className="mt-3">
          <ReportTableView table={answer.table} />
        </div>
      )}
      {answer.notes && answer.notes.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-ink-600">
          {answer.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
      {answer.link && (
        <Link to={answer.link} className="mt-3 inline-block text-sm font-semibold text-amber-700 hover:underline">
          Open the full report
        </Link>
      )}
    </article>
  )
}

/** /admin/assistant — ask about the business in plain words; answers come from the reports. */
export function AdminAssistantPage() {
  usePageMeta('Business assistant')
  const status = useAssistantStatus()
  const history = useAssistantHistory()
  const ask = useAsk()
  const [text, setText] = useState('')
  const [store, setStore] = useState('')
  const [answers, setAnswers] = useState<AssistantAnswer[]>([])

  function send(question: string) {
    const q = question.trim()
    if (!q) return
    ask.mutate(
      { question: q, store },
      {
        onSuccess: (answer) => {
          setAnswers((current) => [answer, ...current])
          setText('')
        },
      },
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    send(text)
  }

  const ai = status.data?.ai
  return (
    <>
      <PageHeader
        title="Business assistant"
        description={
          <>
            Ask about sales, orders, products, stock, delivery, riders, customers, returns, offers or stores. Answers are calculated
            from your data{' '}
            {ai?.available ? `and worded by the local model (${ai.model}); it can't change or add numbers.` : 'by the built-in rules (no AI model is switched on).'}
          </>
        }
        actions={<StoreSelect value={store} onChange={setStore} />}
      />
      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor="business-question" className="sr-only">
          Your question
        </label>
        <input
          id="business-question"
          className="input flex-1"
          maxLength={300}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. How much did we sell last month compared to the month before?"
        />
        <button type="submit" className="btn-primary" disabled={ask.isPending || !text.trim()}>
          {ask.isPending ? 'Working it out…' : 'Ask'}
        </button>
      </form>
      {ask.isError && (
        <p role="alert" className="mt-2 text-sm text-danger-600">
          {errorMessage(ask.error)}
        </p>
      )}
      {(status.data?.suggestions.length ?? 0) > 0 && (
        <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Suggested questions">
          {status.data!.suggestions.map((s) => (
            <button key={s} type="button" className="rounded-full bg-white px-3 py-1.5 text-sm ring-1 ring-steel-200 hover:ring-amber-500" onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_18rem]">
        <section aria-label="Answers" className="space-y-4" aria-live="polite">
          {answers.length === 0 && <p className="text-sm text-ink-600">Your answers appear here.</p>}
          {answers.map((answer, index) => (
            <AnswerCard key={`${answer.question}-${answers.length - index}`} answer={answer} />
          ))}
        </section>
        <Panel title="Earlier questions">
          {history.data && history.data.length > 0 ? (
            <ul className="space-y-2 text-sm">
              {history.data.slice(0, 15).map((row) => (
                <li key={row.id}>
                  <button type="button" className="text-left hover:text-amber-700 hover:underline" onClick={() => send(row.question)}>
                    {row.question}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-600">None yet.</p>
          )}
        </Panel>
      </div>
    </>
  )
}
