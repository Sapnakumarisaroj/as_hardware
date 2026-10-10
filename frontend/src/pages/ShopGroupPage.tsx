import { useParams } from 'react-router'

import { Breadcrumbs } from '@/components/Breadcrumbs'
import { ErrorState, PageSpinner } from '@/components/feedback'
import { GroupDepartments } from '@/features/catalog/components/GroupDepartments'
import { ProductRail } from '@/features/catalog/components/ProductCollections'
import { NAV_GROUPS, useNavGroups } from '@/features/catalog/navGroups'
import { pluralize } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

import { NotFoundPage } from './NotFoundPage'

/** /shop/:group — one of the four navigation groups: its departments (the real catalogue categories,
 * with their own subcategories) and a product rail for each. */
export function ShopGroupPage() {
  const { group: slug = '' } = useParams()
  const { groups, categories } = useNavGroups()
  const known = NAV_GROUPS.find((g) => g.slug === slug)
  const group = groups.find((g) => g.slug === slug)
  usePageMeta(known?.name ?? null, known?.blurb)

  if (!known) return <NotFoundPage />
  if (categories.isPending) return <PageSpinner label="Loading categories…" />
  if (categories.isError) {
    return (
      <div className="container-page py-10">
        <ErrorState error={categories.error} onRetry={() => categories.refetch()} title="Couldn’t load this section" />
      </div>
    )
  }
  if (!group) return <NotFoundPage />

  return (
    <>
      <div className="border-b border-steel-200 bg-white">
        <div className="container-page py-5">
          <Breadcrumbs items={[{ label: group.name }]} />
          <h1 className="mt-2 text-2xl font-extrabold text-ink-950 sm:text-3xl">{group.name}</h1>
          <p className="mt-1 max-w-3xl text-sm text-ink-800">
            {group.blurb}
            {group.productCount !== null && <span className="text-ink-600"> · {pluralize(group.productCount, 'product')}</span>}
          </p>
          <GroupDepartments group={group} className="mt-5" />
        </div>
      </div>
      <div className="container-page">
        {group.entries.map((entry) => (
          <ProductRail
            key={entry.slug}
            title={entry.name}
            params={{ category: entry.slug, ordering: 'popular', in_stock: 'true' }}
            viewAllHref={entry.href}
          />
        ))}
      </div>
    </>
  )
}
