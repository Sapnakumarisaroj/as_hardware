import { useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { CameraIcon, ClockIcon, CloseIcon, SearchIcon } from '@/components/icons'
import { useAuth } from '@/features/auth/context'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { formatPrice } from '@/lib/format'

import { useClearRecentSearches, useDebouncedValue, useRecentSearches, useRecordSearch, useSuggestions } from './api'

interface Option {
  key: string
  href: string
  label: string
  detail?: string
  image?: string | null
  kind: 'query' | 'product' | 'category' | 'brand' | 'recent'
  /** The search words, for options that run a search (remembered as a recent search). */
  query?: string
}

const KIND_LABEL: Record<Option['kind'], string> = {
  query: 'Search',
  product: 'Product',
  category: 'Category',
  brand: 'Brand',
  recent: 'Recent search',
}

/** Header search with type-ahead suggestions and (for signed-in users) recent searches. */
export function SearchBar({ initialQuery = '', autoFocus = false }: { initialQuery?: string; autoFocus?: boolean }) {
  const [value, setValue] = useState(initialQuery)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const { status } = useAuth()

  const debounced = useDebouncedValue(value)
  const typed = debounced.trim()
  const suggestions = useSuggestions(typed)
  const recent = useRecentSearches()
  const recordSearch = useRecordSearch()
  const clearRecent = useClearRecentSearches()

  const options = useMemo<Option[]>(() => {
    if (typed.length >= 2) {
      const data = suggestions.data
      return [
        {
          key: 'q',
          kind: 'query',
          label: `Search for “${typed}”`,
          query: typed,
          href: `/search?q=${encodeURIComponent(typed)}`,
        },
        ...(data?.products ?? []).map<Option>((p) => ({
          key: `p-${p.id}`,
          kind: 'product',
          label: p.name,
          detail: [p.price ? formatPrice(p.price) : '', p.match_reason ?? ''].filter(Boolean).join(' · ') || undefined,
          image: p.image,
          href: `/p/${p.slug}`,
        })),
        ...(data?.categories ?? []).map<Option>((c) => ({
          key: `c-${c.slug}`,
          kind: 'category',
          label: c.name,
          detail: c.parent_name ? `in ${c.parent_name}` : undefined,
          href: `/c/${c.slug}`,
        })),
        ...(data?.brands ?? []).map<Option>((b) => ({
          key: `b-${b.slug}`,
          kind: 'brand',
          label: b.name,
          href: `/search?brand=${encodeURIComponent(b.slug)}`,
        })),
      ]
    }
    if (!value.trim() && status === 'authenticated') {
      return (recent.data ?? []).slice(0, 6).map<Option>((r) => ({
        key: `r-${r.query}`,
        kind: 'recent',
        label: r.query,
        query: r.query,
        href: `/search?q=${encodeURIComponent(r.query)}`,
      }))
    }
    return []
  }, [typed, value, suggestions.data, recent.data, status])

  const showList = open && options.length > 0
  const loading = value.trim().length >= 2 && (suggestions.isFetching || debounced !== value)

  function go(option: Option) {
    if (option.query) recordSearch.mutate(option.query)
    setOpen(false)
    setActive(-1)
    inputRef.current?.blur()
    navigate(option.href)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const selected = active >= 0 ? options[active] : undefined
    if (selected) return go(selected)
    const q = value.trim()
    if (!q) return
    recordSearch.mutate(q)
    setOpen(false)
    inputRef.current?.blur()
    navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && options.length) {
      event.preventDefault()
      setOpen(true)
      setActive((i) => (i + 1) % options.length)
    } else if (event.key === 'ArrowUp' && options.length) {
      event.preventDefault()
      setActive((i) => (i <= 0 ? options.length - 1 : i - 1))
    } else if (event.key === 'Escape') {
      setOpen(false)
      setActive(-1)
    }
  }

  const activeOption = active >= 0 ? options[active] : undefined

  return (
    <form role="search" onSubmit={submit} className="relative w-full">
      <label htmlFor={`${listId}-input`} className="sr-only">
        Search products
      </label>
      <div className="flex items-center rounded-md bg-white ring-1 ring-steel-200 focus-within:ring-2 focus-within:ring-amber-500">
        <SearchIcon className="ml-3 size-4 shrink-0 text-ink-600" />
        <input
          id={`${listId}-input`}
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={showList}
          aria-controls={`${listId}-list`}
          aria-autocomplete="list"
          aria-activedescendant={activeOption ? `${listId}-${activeOption.key}` : undefined}
          autoComplete="off"
          enterKeyHint="search"
          autoFocus={autoFocus}
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            setOpen(true)
            setActive(-1)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          placeholder="Search drills, pipes, 1.5 sq mm wire…"
          maxLength={100}
          className="min-w-0 flex-1 bg-transparent px-2 py-2.5 text-sm text-ink-900 placeholder:text-steel-400 focus:outline-none [&::-webkit-search-cancel-button]:hidden"
        />
        {loading && (
          <span
            role="status"
            aria-label="Loading suggestions"
            className="mr-2 size-4 animate-spin rounded-full border-2 border-steel-200 border-t-amber-500"
          />
        )}
        {value && (
          <button
            type="button"
            onClick={() => {
              setValue('')
              setActive(-1)
              inputRef.current?.focus()
            }}
            aria-label="Clear search"
            className="p-2 text-ink-600 hover:text-ink-900"
          >
            <CloseIcon className="size-4" />
          </button>
        )}
        <Link
          to="/image-search"
          aria-label="Search by photo"
          title="Search by photo"
          className="p-2 text-ink-600 hover:text-amber-600 focus-visible:text-amber-600"
        >
          <CameraIcon className="size-5" />
        </Link>
        <button type="submit" className="rounded-r-md bg-amber-500 px-3 py-2.5 text-ink-950 hover:bg-amber-600" aria-label="Search">
          <SearchIcon className="size-4" />
        </button>
      </div>

      {showList && (
        <div className="absolute inset-x-0 top-full z-40 mt-1 overflow-hidden rounded-md bg-white text-ink-900 shadow-lg ring-1 ring-steel-200">
          {options[0]?.kind === 'recent' && (
            <div className="flex items-center justify-between border-b border-steel-100 px-3 py-2 text-xs text-ink-600">
              <span>Recent searches</span>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => clearRecent.mutate()}
                className="font-semibold text-amber-600 hover:underline"
              >
                Clear
              </button>
            </div>
          )}
          <ul id={`${listId}-list`} role="listbox" aria-label="Search suggestions" className="max-h-96 overflow-y-auto py-1">
            {options.map((option, index) => (
              <li
                key={option.key}
                id={`${listId}-${option.key}`}
                role="option"
                aria-selected={index === active}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => go(option)}
                onMouseEnter={() => setActive(index)}
                className={`flex cursor-pointer items-center gap-3 px-3 py-2 text-sm ${index === active ? 'bg-steel-100' : ''}`}
              >
                {option.kind === 'product' ? (
                  <ProductImage src={option.image} alt="" className="size-9 shrink-0 rounded" />
                ) : option.kind === 'recent' ? (
                  <ClockIcon className="size-4 shrink-0 text-ink-600" />
                ) : (
                  <SearchIcon className="size-4 shrink-0 text-ink-600" />
                )}
                <span className="min-w-0 flex-1 truncate">
                  {option.label}
                  {option.detail && <span className="ml-2 text-xs text-ink-600">{option.detail}</span>}
                </span>
                <span className="shrink-0 text-xs text-steel-400">{KIND_LABEL[option.kind]}</span>
              </li>
            ))}
          </ul>
          {typed.length >= 2 && suggestions.isSuccess && options.length === 1 && (
            <p className="border-t border-steel-100 px-3 py-2 text-xs text-ink-600">No quick matches — press Enter to search.</p>
          )}
        </div>
      )}
    </form>
  )
}
