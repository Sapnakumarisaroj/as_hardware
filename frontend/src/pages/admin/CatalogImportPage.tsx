import { useRef, useState } from 'react'
import { Link } from 'react-router'

import { useToast } from '@/components/toast'
import { downloadCatalogFile, useCatalogImport } from '@/features/admin/api'
import { useSession } from '@/features/admin/session'
import type { CatalogImportReport } from '@/features/admin/types'
import { Badge, DataTable, errorMessage, NotAllowed, PageHeader, Panel, type Column } from '@/features/admin/ui'
import { usePageMeta } from '@/lib/usePageMeta'

type ErrorRow = CatalogImportReport['errors'][number]
type ResultRow = CatalogImportReport['rows'][number]

const ACTIONS: Record<ResultRow['action'], [string, 'good' | 'info' | 'neutral']> = {
  create: ['New', 'good'],
  update: ['Changed', 'info'],
  unchanged: ['No change', 'neutral'],
}

const COUNT_LABELS: [string, string][] = [
  ['products_created', 'New products'],
  ['products_updated', 'Changed products'],
  ['variants_created', 'New variants'],
  ['variants_updated', 'Changed variants'],
  ['unchanged', 'Unchanged variants'],
  ['stock_movements', 'Stock adjustments'],
  ['brands_created', 'New brands'],
]

const errorColumns: Column<ErrorRow>[] = [
  { header: 'Row', numeric: true, cell: (error) => error.row ?? 'File' },
  { header: 'Column', cell: (error) => error.column || '—' },
  { header: 'SKU', cell: (error) => error.sku || '—' },
  { header: 'Problem', cell: (error) => error.message },
]

const resultColumns: Column<ResultRow>[] = [
  { header: 'Row', numeric: true, cell: (row) => row.row },
  { header: 'Product SKU', cell: (row) => row.product_sku },
  { header: 'Variant SKU', cell: (row) => row.variant_sku },
  {
    header: 'Result',
    cell: (row) => {
      const [text, tone] = ACTIONS[row.action]
      return <Badge tone={tone}>{text}</Badge>
    },
  },
]

function Result({ report }: { report: CatalogImportReport }) {
  if (!report.ok) {
    return (
      <div className="mt-4 space-y-3">
        <p role="alert" className="rounded-md bg-danger-600/10 p-3 text-sm font-semibold text-danger-600">
          {report.errors.length === 1 ? '1 problem' : `${report.errors.length} problems`} found in {report.filename}. Nothing
          was saved. Fix the rows below and check the file again.
        </p>
        <DataTable caption="Problems in the file" columns={errorColumns} rows={report.errors} rowKey={(e) => `${e.row}-${e.column}-${e.message}`} />
      </div>
    )
  }
  const counts = COUNT_LABELS.filter(([key]) => (report.counts[key] ?? 0) > 0)
  return (
    <div className="mt-4 space-y-3">
      <p role="status" className="rounded-md bg-success-600/10 p-3 text-sm font-semibold text-success-600">
        {report.committed
          ? `Imported ${report.filename}: ${report.counts.rows} rows saved.`
          : `${report.filename}: all ${report.counts.rows} rows are fine. Nothing has been saved yet.`}
      </p>
      {counts.length > 0 && (
        <ul className="flex flex-wrap gap-2 text-sm">
          {counts.map(([key, text]) => (
            <li key={key} className="rounded-md bg-steel-50 px-3 py-1.5 ring-1 ring-steel-200">
              {text}: <strong>{report.counts[key]}</strong>
            </li>
          ))}
        </ul>
      )}
      <DataTable caption={report.committed ? 'Imported rows' : 'What the import will do'} columns={resultColumns} rows={report.rows} rowKey={(r) => r.row} />
    </div>
  )
}

export function AdminCatalogImportPage() {
  usePageMeta('Import / export')
  const session = useSession()
  const toast = useToast()
  const run = useCatalogImport()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<CatalogImportReport | null>(null)
  const [downloading, setDownloading] = useState('')

  if (!session.can.manage_catalog) return <NotAllowed what="Catalogue imports" />

  const send = (dryRun: boolean) => {
    if (!file) return
    run.mutate(
      { file, dryRun },
      {
        onSuccess: (result) => {
          setReport(result)
          if (result.committed) {
            toast.show(`Imported ${result.counts.rows} rows.`)
            setFile(null)
            if (input.current) input.current.value = ''
          }
        },
        onError: () => setReport(null),
      },
    )
  }

  const download = async (kind: 'export' | 'template', format: 'xlsx' | 'csv') => {
    setDownloading(`${kind}-${format}`)
    try {
      await downloadCatalogFile(kind, format)
    } catch (error) {
      toast.show(errorMessage(error), { tone: 'error' })
    } finally {
      setDownloading('')
    }
  }

  const button = (kind: 'export' | 'template', format: 'xlsx' | 'csv', text: string) => (
    <button type="button" className="btn-secondary" disabled={downloading !== ''} onClick={() => void download(kind, format)}>
      {downloading === `${kind}-${format}` ? 'Preparing…' : text}
    </button>
  )

  const canCommit = report !== null && report.ok && report.dry_run && file !== null

  return (
    <>
      <PageHeader
        title="Import / export"
        crumbs={[{ label: 'Products', to: '/admin/products' }]}
        description="Add or update many products at once from a spreadsheet, one row per variant. Export the catalogue, change it in Excel and import it again."
      />
      <div className="grid gap-4">
        <Panel title="Download">
          <div className="flex flex-wrap gap-2">
            {button('export', 'xlsx', 'Export catalogue (Excel)')}
            {button('export', 'csv', 'Export catalogue (CSV)')}
            {button('template', 'xlsx', 'Blank template (Excel)')}
            {button('template', 'csv', 'Blank template (CSV)')}
          </div>
          <p className="mt-2 text-xs text-ink-600">
            The export includes purchase costs, so keep it inside the business. Demo products are left out. The Excel template has a
            “Columns” sheet that explains every column.
          </p>
        </Panel>

        <Panel title="Import">
          <label htmlFor="catalog-file" className="label">
            Spreadsheet (.xlsx or .csv, up to 5 MB)
          </label>
          <input
            ref={input}
            id="catalog-file"
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={run.isPending}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-ink-900 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
              setReport(null)
              run.reset()
            }}
          />
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-ink-600">
            <li>Existing SKUs are updated, new SKUs are added. Columns you leave out of the file are not changed.</li>
            <li>Stock is the quantity available at each store (e.g. BLR-01:25); the difference is booked as a stock adjustment.</li>
            <li>Pictures are not imported: add them on each product’s page.</li>
          </ul>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" disabled={!file || run.isPending} onClick={() => send(true)}>
              {run.isPending && run.variables?.dryRun ? 'Checking…' : 'Check file'}
            </button>
            {canCommit && (
              <button type="button" className="btn-primary" disabled={run.isPending} onClick={() => send(false)}>
                {run.isPending && !run.variables?.dryRun ? 'Importing…' : `Import ${report.counts.rows} rows`}
              </button>
            )}
          </div>
          {run.error && (
            <p role="alert" className="mt-3 text-sm font-semibold text-danger-600">
              {errorMessage(run.error)}
            </p>
          )}
          {report && <Result report={report} />}
          {report?.committed && (
            <p className="mt-3 text-sm">
              <Link to="/admin/products" className="font-semibold underline-offset-2 hover:underline">
                Back to products
              </Link>
            </p>
          )}
        </Panel>
      </div>
    </>
  )
}
