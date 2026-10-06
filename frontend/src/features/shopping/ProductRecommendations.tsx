import type { ReactNode } from 'react'

import { useHomeRecommendations, useProductRecommendations } from './api'
import { BundleCard, RecommendationRails } from './components'

const PRODUCT_ORDER = ['needed_with', 'frequently_bought_together', 'works_with', 'better_alternatives', 'complete_the_project', 'best_value', 'popular_in_category']
const PRODUCT_TITLES = { frequently_bought_together: 'Buy together', works_with: 'Compatible products' }
const HOME_ORDER = ['buy_again', 'recommended_for_you', 'complete_your_project', 'best_value', 'popular_now']

/** Product page: buy together, needed with this, compatible products, alternatives, complete the project (Phase 22). */
export function ProductRecommendations({ productId, variantId, fallback }: { productId: number; variantId: number | null; fallback: ReactNode }) {
  const data = useProductRecommendations(productId, variantId)
  if (!data.data) return <>{data.isError ? fallback : null}</>
  const hasGroups = PRODUCT_ORDER.some((name) => (data.data.groups[name] ?? []).length > 0)
  return (
    <div>
      {hasGroups ? <RecommendationRails data={data.data} order={PRODUCT_ORDER} titles={PRODUCT_TITLES} /> : fallback}
      {(data.data.bundles ?? []).length > 0 && (
        <section aria-label="Complete the project with a kit" className="py-4">
          <h2 className="mb-3 text-lg font-bold text-ink-950">Complete the project with a kit</h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.data.bundles!.map((bundle) => (
              <BundleCard key={bundle.id} bundle={bundle} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

/** Home page: buy again and "based on your orders" only from the customer's own history; everyone sees best value. */
export function HomeRecommendations() {
  const data = useHomeRecommendations()
  if (!data.data) return null
  return <RecommendationRails data={data.data} order={HOME_ORDER} />
}
