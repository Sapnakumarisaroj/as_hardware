import type { AdminCategory } from './types'

/** Departments and categories (levels 1–2) can hold products; a product's subcategory is a child of its category. */
export function flattenCategories(tree: AdminCategory[]): { category: AdminCategory; path: string; level: number }[] {
  const out: { category: AdminCategory; path: string; level: number }[] = []
  const walk = (nodes: AdminCategory[], prefix: string, level: number) => {
    for (const node of nodes) {
      const path = prefix ? `${prefix} › ${node.name}` : node.name
      out.push({ category: node, path, level })
      walk(node.children ?? [], path, level + 1)
    }
  }
  walk(tree, '', 1)
  return out
}
