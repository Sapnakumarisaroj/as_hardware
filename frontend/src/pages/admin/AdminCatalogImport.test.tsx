import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CatalogImportReport } from '@/features/admin/types'
import { page, productRow, staffGet } from '@/test/adminFixtures'
import { httpError, mockApi, type RequestInfo } from '@/test/mockApi'
import { renderRoute, signIn } from '@/test/utils'

function report(overrides: Partial<CatalogImportReport> = {}): CatalogImportReport {
  return {
    ok: true,
    dry_run: true,
    committed: false,
    filename: 'catalogue.csv',
    counts: { rows: 2, products_created: 1, variants_created: 2, stock_movements: 1 },
    rows: [
      { row: 2, product_sku: 'DR-500', variant_sku: 'DR-500-STD', action: 'create' },
      { row: 3, product_sku: 'DR-500', variant_sku: 'DR-500-KIT', action: 'create' },
    ],
    errors: [],
    ...overrides,
  }
}

const sheet = () => new File(['product_sku,variant_sku\nDR-500,DR-500-STD\n'], 'catalogue.csv', { type: 'text/csv' })

describe('catalogue import', () => {
  it('checks the file first, then imports it', async () => {
    signIn()
    const sent: string[] = []
    const api = mockApi({
      get: staffGet('admin'),
      post: {
        '/admin/catalog/import/': ({ body }: RequestInfo) => {
          const dryRun = (body as FormData).get('dry_run') as string
          sent.push(dryRun)
          return dryRun === 'true' ? report() : report({ dry_run: false, committed: true })
        },
      },
    })
    const { user } = renderRoute('/admin/products/import')
    const check = await screen.findByRole('button', { name: 'Check file' })
    expect(check).toBeDisabled()
    await user.upload(screen.getByLabelText(/Spreadsheet/), sheet())
    await user.click(check)

    expect(await screen.findByText(/all 2 rows are fine/)).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'What the import will do' })
    expect(within(table).getAllByText('New')).toHaveLength(2)
    expect(screen.getByText('New products:')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Import 2 rows' }))
    expect(await screen.findByText(/Imported catalogue.csv: 2 rows saved/)).toBeInTheDocument()
    expect(sent).toEqual(['true', 'false'])
    expect((api.post.mock.calls.at(0)?.[1] as FormData).get('file')).toBeInstanceOf(File)
    expect(screen.queryByRole('button', { name: /Import \d+ rows/ })).not.toBeInTheDocument()
  })

  it('lists row errors and offers no import', async () => {
    signIn()
    mockApi({
      get: staffGet('admin'),
      post: {
        '/admin/catalog/import/': report({
          ok: false,
          rows: [],
          errors: [{ row: 2, column: 'price', sku: 'DR-500-STD', message: 'The price ₹3300 is above the MRP ₹3200.' }],
        }),
      },
    })
    const { user } = renderRoute('/admin/products/import')
    await user.upload(await screen.findByLabelText(/Spreadsheet/), sheet())
    await user.click(screen.getByRole('button', { name: 'Check file' }))
    expect(await screen.findByText(/1 problem found in catalogue.csv/)).toBeInTheDocument()
    const row = within(screen.getByRole('table', { name: 'Problems in the file' })).getByRole('row', { name: /DR-500-STD/ })
    expect(within(row).getByText('price')).toBeInTheDocument()
    expect(within(row).getByText(/above the MRP/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Import \d+ rows/ })).not.toBeInTheDocument()
  })

  it('shows a file-level error', async () => {
    signIn()
    mockApi({
      get: staffGet('admin'),
      post: { '/admin/catalog/import/': httpError(400, 'Upload a .csv or .xlsx file.', 'unsupported_file_type') },
    })
    const { user } = renderRoute('/admin/products/import')
    await user.upload(await screen.findByLabelText(/Spreadsheet/), sheet())
    await user.click(screen.getByRole('button', { name: 'Check file' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Upload a .csv or .xlsx file.')
  })

  it('downloads the export and the template', async () => {
    signIn()
    const api = mockApi({
      get: staffGet('admin', { '/admin/catalog/export/': new Blob(['x']), '/admin/catalog/template/': new Blob(['x']) }),
    })
    const { user } = renderRoute('/admin/products/import')
    await user.click(await screen.findByRole('button', { name: 'Export catalogue (CSV)' }))
    await user.click(screen.getByRole('button', { name: 'Blank template (Excel)' }))
    const calls = api.get.mock.calls.filter(([url]) => String(url).startsWith('/admin/catalog/'))
    expect(calls.map(([url, config]) => [url, (config as { params: { format: string } }).params.format])).toEqual([
      ['/admin/catalog/export/', 'csv'],
      ['/admin/catalog/template/', 'xlsx'],
    ])
  })

  it('is for administrators only', async () => {
    signIn()
    mockApi({ get: staffGet('manager') })
    renderRoute('/admin/products/import')
    expect(await screen.findByText('For administrators only')).toBeInTheDocument()
  })

  it('marks demo products in the product list and links to the import', async () => {
    signIn()
    mockApi({
      get: staffGet('admin', {
        '/admin/categories/': [],
        '/admin/products/': page([productRow({ is_demo: true })]),
      }),
    })
    renderRoute('/admin/products')
    const table = await screen.findByRole('table', { name: 'Products' })
    expect(within(table).getByText('Demo')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Import / export' })).toHaveAttribute('href', '/admin/products/import')
  })
})
