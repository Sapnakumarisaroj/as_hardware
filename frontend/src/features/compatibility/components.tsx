import { Link } from 'react-router'

import { formatPrice } from '@/lib/format'

import type { CompatibilityOption, CompatibilityProblem, CompatibilityResult, Verdict } from './types'

const VERDICT: Record<Verdict, { icon: string; text: string; tone: string }> = {
  COMPATIBLE: { icon: '✅', text: 'Compatible', tone: 'border-success-600/40 bg-success-600/5' },
  POSSIBLY_COMPATIBLE: { icon: '⚠️', text: 'Possibly compatible', tone: 'border-amber-300 bg-amber-50' },
  NOT_COMPATIBLE: { icon: '❌', text: 'Not compatible', tone: 'border-danger-600/40 bg-danger-600/5' },
  INSUFFICIENT_INFORMATION: { icon: 'ℹ️', text: 'Not enough information', tone: 'border-steel-200 bg-steel-50' },
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const v = VERDICT[verdict]
  return (
    <span className="font-semibold">
      <span aria-hidden>{v.icon} </span>
      {v.text}
    </span>
  )
}

const CHECK_ICON = { pass: '✓', fail: '✗', warn: '!', missing: '?' } as const

/** A verdict with its reason and the facts checked. */
export function CompatibilityResultCard({ result, onUse }: { result: CompatibilityResult; onUse?: (option: CompatibilityOption) => void }) {
  return (
    <div role="status" className={`rounded-lg border p-3 text-sm ${VERDICT[result.verdict].tone}`}>
      <p>
        <VerdictBadge verdict={result.verdict} />
      </p>
      <p className="mt-1">
        <span className="font-medium">Reason: </span>
        {result.reason}
      </p>
      {result.checks.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-ink-700" aria-label="What was checked">
          {result.checks.map((check) => (
            <li key={`${check.name}-${check.detail}`}>
              <span aria-hidden className="mr-1 font-bold">
                {CHECK_ICON[check.status]}
              </span>
              {check.detail}
            </li>
          ))}
        </ul>
      )}
      {result.sources.some((s) => s.startsWith('relation:')) && <p className="mt-1 text-xs text-ink-600">Includes the shop’s own product links.</p>}
      <Options options={result.options} onUse={onUse} />
    </div>
  )
}

function Options({ options, onUse, label = 'Compatible options' }: { options: CompatibilityOption[]; onUse?: (option: CompatibilityOption) => void; label?: string }) {
  const shown = options.filter((o) => o.product)
  if (!shown.length) return null
  return (
    <div className="mt-2">
      <p className="text-xs font-semibold text-ink-700">{label}</p>
      <ul className="mt-1 space-y-1" aria-label={label}>
        {shown.map((option) => (
          <li key={option.product_id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-white px-2 py-1 ring-1 ring-steel-200">
            <Link to={`/p/${option.product!.slug}`} className="text-sm hover:text-amber-600">
              {option.product!.name} · {formatPrice(option.product!.price)}
            </Link>
            {onUse && (
              <button type="button" className="text-xs font-semibold text-amber-700 underline" onClick={() => onUse(option)}>
                Use this instead
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Lines that may not work together (project kit, quantity result, cart), with replacements. */
export function CompatibilityProblems({
  problems,
  onReplace,
  replaceLabel = 'Replace with this',
}: {
  problems: CompatibilityProblem[]
  onReplace?: (problem: CompatibilityProblem, option: CompatibilityOption) => void
  replaceLabel?: string
}) {
  if (!problems.length) return null
  return (
    <section aria-label="Compatibility" className="space-y-2">
      {problems.map((problem) => (
        <div key={`${problem.product_a.id}-${problem.product_b.id}`} role="alert" className={`rounded-lg border p-3 text-sm ${VERDICT[problem.verdict].tone}`}>
          <p>
            <VerdictBadge verdict={problem.verdict} />
          </p>
          <p className="mt-1">{problem.message}</p>
          {problem.options.length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs font-semibold text-amber-700">View compatible options</summary>
              <ul className="mt-1 space-y-1">
                {problem.options
                  .filter((o) => o.product)
                  .map((option) => (
                    <li key={option.product_id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-white px-2 py-1 ring-1 ring-steel-200">
                      <span>
                        {option.product!.name} · {formatPrice(option.product!.price)}
                      </span>
                      {onReplace && (
                        <button type="button" className="text-xs font-semibold text-amber-700 underline" onClick={() => onReplace(problem, option)}>
                          {replaceLabel}
                        </button>
                      )}
                    </li>
                  ))}
              </ul>
            </details>
          )}
        </div>
      ))}
    </section>
  )
}
