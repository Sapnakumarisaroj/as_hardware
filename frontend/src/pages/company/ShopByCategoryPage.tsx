import { Link } from 'react-router'

import { ChevronRightIcon } from '@/components/icons'
import { GroupDepartments } from '@/features/catalog/components/GroupDepartments'
import { useNavGroups } from '@/features/catalog/navGroups'
import { InfoPage } from '@/features/company/InfoPage'
import { pluralize } from '@/lib/format'

/** /shop-by-category — the four groups and all their departments on one page (same data as the menu). */
export function ShopByCategoryPage() {
  const { groups } = useNavGroups()
  return (
    <InfoPage
      group="company"
      wide
      title="Shop by Category"
      intro="Every department in our catalogue, arranged in the same four groups as the main menu."
    >
      {groups.map((group) => (
        <section key={group.slug} aria-labelledby={`group-${group.slug}`} className="mt-10 first:mt-0">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 id={`group-${group.slug}`} className="mt-0!">
                {group.name}
              </h2>
              <p className="mt-1 text-sm text-ink-600">
                {group.blurb}
                {group.productCount !== null && ` · ${pluralize(group.productCount, 'product')}`}
              </p>
            </div>
            <Link to={group.href} className="inline-flex items-center gap-1 text-sm font-semibold text-ink-950 hover:text-amber-700">
              View {group.name}
              <ChevronRightIcon className="size-4" />
            </Link>
          </div>
          <GroupDepartments group={group} className="mt-4" />
        </section>
      ))}
    </InfoPage>
  )
}
