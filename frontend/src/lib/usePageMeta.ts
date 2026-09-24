import { useEffect } from 'react'

import { env } from '@/lib/env'

const DEFAULT_DESCRIPTION =
  'Hardware, tools, electrical and plumbing supplies from local stores, with clear prices and live stock.'

/** Sets the document title and meta description for the current page (basic SEO). */
export function usePageMeta(title: string | null | undefined, description?: string | null) {
  useEffect(() => {
    document.title = title ? `${title} | ${env.appName}` : `${env.appName} — Hardware & tools`
    let meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
    if (!meta) {
      meta = document.createElement('meta')
      meta.name = 'description'
      document.head.appendChild(meta)
    }
    meta.content = (description || DEFAULT_DESCRIPTION).slice(0, 160)
  }, [title, description])
}
