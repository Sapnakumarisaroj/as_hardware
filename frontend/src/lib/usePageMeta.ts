import { useEffect } from 'react'
import { useLocation } from 'react-router'

import { env } from '@/lib/env'

const DEFAULT_DESCRIPTION =
  'Hardware, tools, electrical and plumbing supplies from local stores, with clear prices and live stock.'

/** Query parameters that don't change what a page is (filters/sorting/paging stay out of the canonical URL). */
const CANONICAL_PARAMS = new Set<string>()

interface PageMetaOptions {
  /** Open Graph type: `product` on product pages, `website` elsewhere. */
  type?: 'website' | 'product'
  image?: string | null
  /** Structured data (schema.org JSON-LD) for this page, e.g. a Product with its offer. */
  jsonLd?: Record<string, unknown> | null
}

function setMeta(attribute: 'name' | 'property', key: string, content: string | null) {
  let element = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`)
  if (!content) {
    element?.remove()
    return
  }
  if (!element) {
    element = document.createElement('meta')
    element.setAttribute(attribute, key)
    document.head.appendChild(element)
  }
  element.content = content
}

function canonicalUrl(pathname: string, search: string): string {
  const params = new URLSearchParams(search)
  const kept = new URLSearchParams()
  params.forEach((value, key) => {
    if (CANONICAL_PARAMS.has(key)) kept.set(key, value)
  })
  const query = kept.toString()
  return `${window.location.origin}${pathname}${query ? `?${query}` : ''}`
}

/**
 * Title, description, canonical URL, Open Graph tags and optional JSON-LD for the current page (basic
 * client-side SEO; the sitemap is served by the API at /api/seo/sitemap.xml).
 */
export function usePageMeta(title: string | null | undefined, description?: string | null, options: PageMetaOptions = {}) {
  const { pathname, search } = useLocation()
  const { type = 'website', image = null, jsonLd = null } = options
  const jsonText = jsonLd ? JSON.stringify(jsonLd) : ''

  useEffect(() => {
    const fullTitle = title ? `${title} | ${env.appName}` : `${env.appName} — Hardware & tools`
    const text = (description || DEFAULT_DESCRIPTION).slice(0, 160)
    document.title = fullTitle
    setMeta('name', 'description', text)
    setMeta('property', 'og:title', fullTitle)
    setMeta('property', 'og:description', text)
    setMeta('property', 'og:type', type)
    setMeta('property', 'og:image', image)

    let link = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (!link) {
      link = document.createElement('link')
      link.rel = 'canonical'
      document.head.appendChild(link)
    }
    link.href = canonicalUrl(pathname, search)
    setMeta('property', 'og:url', link.href)
  }, [title, description, type, image, pathname, search])

  useEffect(() => {
    if (!jsonText) return
    const script = document.createElement('script')
    script.type = 'application/ld+json'
    script.dataset.pageMeta = 'true'
    script.textContent = jsonText
    document.head.appendChild(script)
    return () => script.remove()
  }, [jsonText])
}
