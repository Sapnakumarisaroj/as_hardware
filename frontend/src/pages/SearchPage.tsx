import { useSearchParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { ProductBrowser } from '@/features/catalog/components/ProductBrowser'
import { usePageMeta } from '@/lib/usePageMeta'

/** /search?q=… and /products (everything) share the same listing experience. */
export function SearchPage({ mode }: { mode: 'search' | 'all' }) {
  const [params] = useSearchParams()
  const q = params.get('q')?.trim() ?? ''
  const title = mode === 'search' && q ? `Results for “${q}”` : 'All products'
  usePageMeta(mode === 'search' && q ? `Search: ${q}` : 'All products')

  return (
    <>
      <div className="border-b border-steel-200 bg-white">
        <div className="container-page py-4">
          <Breadcrumbs items={[{ label: mode === 'search' ? 'Search' : 'All products' }]} />
        </div>
      </div>
      <ProductBrowser heading={<h1 className="text-2xl font-bold text-ink-950">{title}</h1>} />
    </>
  )
}
