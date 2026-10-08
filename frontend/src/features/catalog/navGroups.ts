import { useMemo } from 'react'

import { useCategories } from './api'
import type { Category, SubCategory } from './types'

/*
 * The storefront's four navigation groups: a presentation layer over the shop's ten approved
 * departments (backend apps/catalog/taxonomy.py, same slugs and names), which stay the real catalogue
 * categories. The groups and department links always render from this table, so the navigation never
 * depends on the category request succeeding. Once the catalogue API answers, it supplies the live
 * names, product counts, photos and subcategories, and departments without products are left out.
 */

interface NavGroupConfig {
  slug: string
  name: string
  blurb: string
  /** The approved departments in this group, in menu order: [slug, name as in the catalogue]. */
  departments: [slug: string, name: string][]
}

export const NAV_GROUPS: NavGroupConfig[] = [
  {
    slug: 'wood-adhesives',
    name: 'Wood & Adhesives',
    blurb: 'Plywood, MDF and HDHMR boards, and Fevicol adhesives.',
    departments: [
      ['plywood-mdf-hdhmr', 'Plywood, MDF & HDHMR'],
      ['fevicol', 'Fevicol'],
    ],
  },
  {
    slug: 'furniture-hardware',
    name: 'Furniture Hardware',
    blurb: 'Hinges, channels, handles, kitchen systems, wardrobe and bed fittings.',
    departments: [
      ['hinges-channels-handles', 'Hinges, Channels & Handles'],
      ['kitchen-systems', 'Kitchen Systems & Accessories'],
      ['wardrobe-bed-fittings', 'Wardrobe & Bed Fittings'],
    ],
  },
  {
    slug: 'door-glass-hardware',
    name: 'Door & Glass Hardware',
    blurb: 'Door locks and door hardware, glass door handles, patch fittings and floor springs.',
    departments: [
      ['door-locks-hardware', 'Door Locks & Hardware'],
      ['glass-door-hardware', 'Glass Door Hardware'],
    ],
  },
  {
    slug: 'tools-safety',
    name: 'Tools & Safety',
    blurb: 'Power tools and accessories, general hardware and hand tools, safety tools and workwear.',
    departments: [
      ['power-tools', 'Power Tools & Accessories'],
      ['general-hardware', 'General Hardware & Tools'],
      ['safety', 'Safety Tools & Workwear'],
    ],
  },
]

export interface NavLink {
  name: string
  slug: string
  href: string
  productCount: number | null
}

/** One of the shop's departments, exactly as the catalogue names it. */
export interface NavEntry extends NavLink {
  image: string | null
  /** Its own subcategories that have products (from the catalogue, in its order). */
  subcategories: NavLink[]
}

export interface NavGroup {
  slug: string
  name: string
  blurb: string
  href: string
  entries: NavEntry[]
  productCount: number | null
  /** Distinct photos of the group's categories (real product photos from the API), departments first. */
  images: string[]
}

const hasProducts = (c: SubCategory) => c.product_count !== 0
const count = (c: SubCategory) => c.product_count ?? null
const imageOf = (c: SubCategory) => c.cover_image ?? c.image ?? null
const link = (c: SubCategory): NavLink => ({ name: c.name, slug: c.slug, href: `/c/${c.slug}`, productCount: count(c) })

/**
 * The four groups with their departments. Without the category tree (still loading, or the API is
 * unreachable) every group and department is listed from the table, linking to the real category
 * pages. With it, names, counts, photos and subcategories are the catalogue's, and departments the
 * catalogue doesn't have (archived) or has no products in are left out.
 */
export function resolveNavGroups(tree: Category[] | undefined): NavGroup[] {
  const bySlug = new Map((tree ?? []).map((department) => [department.slug, department]))
  const live = Boolean(tree?.length)

  return NAV_GROUPS.flatMap((group) => {
    const entries = group.departments.flatMap(([slug, name]): NavEntry[] => {
      if (!live) return [{ name, slug, href: `/c/${slug}`, productCount: null, image: null, subcategories: [] }]
      const department = bySlug.get(slug)
      if (!department || !hasProducts(department)) return []
      return [{ ...link(department), image: imageOf(department), subcategories: (department.children ?? []).filter(hasProducts).map(link) }]
    })
    if (!entries.length) return []
    const departments = entries.flatMap((entry) => bySlug.get(entry.slug) ?? [])
    const counts = entries.map((e) => e.productCount)
    const photos = [...departments.map(imageOf), ...departments.flatMap((d) => (d.children ?? []).filter(hasProducts).map(imageOf))]
    return [
      {
        slug: group.slug,
        name: group.name,
        blurb: group.blurb,
        href: `/shop/${group.slug}`,
        entries,
        productCount: counts.some((c) => c === null) ? null : counts.reduce<number>((total, c) => total + (c ?? 0), 0),
        images: [...new Set(photos.filter((x): x is string => Boolean(x)))],
      },
    ]
  })
}

/** The four groups from the (cached) category tree, plus the query's loading and error state. */
export function useNavGroups() {
  const categories = useCategories()
  const groups = useMemo(() => resolveNavGroups(categories.data), [categories.data])
  return { groups, categories }
}
