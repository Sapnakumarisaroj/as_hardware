import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { Spinner } from '@/components/feedback'
import { QuantityStepper } from '@/components/QuantityStepper'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { usePincode } from '@/features/delivery/location'
import { optionVariant } from '@/features/compatibility/api'
import { CompatibilityProblems } from '@/features/compatibility/components'
import { Breakdown, PinForm, StockBadge, TotalRow } from '@/features/projects/components'
import type { KitItem, ProjectKit, ProjectQuestion } from '@/features/projects/types'
import { useAddQuantityToCart, useEstimate, useQuantityStatus, useSaveQuantity } from '@/features/quantity/api'
import type {
  AnswerInput,
  QuantityCalculator,
  QuantityMaterial,
  QuantityOverride,
  QuantityRequest,
  QuantityResult,
} from '@/features/quantity/types'
import { ApiError } from '@/lib/api/errors'
import { formatPrice, pluralize } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const EXAMPLES = [
  'Screws and wall plugs for 12 holes in a brick wall',
  'Wall plugs and screws for 8 holes in concrete',
  'Mujhe brick wall mein 10 holes ke liye screw aur plug chahiye',
]

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function amountText(amount: number, unit: string): string {
  const shown = amount >= 10 ? Math.round(amount).toString() : Number(amount.toFixed(2)).toString()
  return `${shown} ${unit}`
}

/** The form's answers as the API takes them: numbers (with their unit when it isn't the question's) or choices. */
function toAnswers(inputs: Record<string, AnswerInput>, questions: ProjectQuestion[]): QuantityRequest['answers'] {
  const out: NonNullable<QuantityRequest['answers']> = {}
  for (const question of questions) {
    const input = inputs[question.key]
    const raw = input?.value.trim() ?? ''
    if (!raw) continue
    if (question.kind === 'choice') out[question.key] = raw
    else if (input?.unit && input.unit !== question.unit) out[question.key] = { value: Number(raw), unit: input.unit }
    else out[question.key] = Number(raw)
  }
  return out
}

export function QuantityPage() {
  usePageMeta('Quantity calculator', 'Work out how many screws, wall plugs and other fixings you need, with real products and prices.')
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const toast = useToast()
  const { status: authStatus } = useAuth()
  const status = useQuantityStatus()
  const estimate = useEstimate()
  const save = useSaveQuantity()
  const savedPin = usePincode()
  const [text, setText] = useState(params.get('q') ?? '')
  const [base, setBase] = useState<{ text?: string; calculator?: string }>({})
  const [inputs, setInputs] = useState<Record<string, AnswerInput>>({})
  const [overrides, setOverrides] = useState<Record<string, QuantityOverride>>({})
  const [pin, setPin] = useState(savedPin)
  const [coupon, setCoupon] = useState('')
  // The last good result stays on screen while a new answer is checked (and when it is refused).
  const [result, setResult] = useState<QuantityResult | undefined>()
  const started = useRef(false)

  function go(request: QuantityRequest) {
    estimate.mutate(request, { onSuccess: setResult })
  }

  function run(next: { base?: typeof base; inputs?: typeof inputs; overrides?: typeof overrides; pin?: string; coupon?: string }) {
    const request: QuantityRequest = {
      ...(next.base ?? base),
      answers: toAnswers(next.inputs ?? inputs, result?.questions ?? []),
      overrides: next.overrides ?? overrides,
      ...((next.pin ?? pin) ? { postal_code: next.pin ?? pin } : {}),
      ...((next.coupon ?? coupon) ? { coupon: next.coupon ?? coupon } : {}),
    }
    go(request)
  }

  function startNew(nextBase: { text?: string; calculator?: string }) {
    setBase(nextBase)
    setInputs({})
    setOverrides({})
    go({ ...nextBase, ...(pin ? { postal_code: pin } : {}) })
  }

  useEffect(() => {
    const q = params.get('q')
    if (q && !started.current) {
      started.current = true
      startNew({ text: q })
    }
    // run once for the link the page was opened with
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (text.trim()) startNew({ text: text.trim() })
  }

  function request(): QuantityRequest {
    return { ...base, answers: toAnswers(inputs, result?.questions ?? []), overrides, ...(pin ? { postal_code: pin } : {}) }
  }

  function onSave() {
    if (authStatus !== 'authenticated') {
      void navigate(`/login?next=${encodeURIComponent(`/quantity?q=${base.text ?? ''}`)}`)
      return
    }
    save.mutate(request(), {
      onSuccess: (saved) => {
        toast.show('Saved to your projects.', { action: { label: 'Open', to: saved.path } })
        void navigate(saved.path)
      },
    })
  }

  const calculators = result?.calculators ?? status.data?.calculators ?? []
  const error: unknown = estimate.error
  const fieldErrors = error instanceof ApiError && error.code === 'invalid_answers' ? (error.details as Record<string, string>) : {}

  return (
    <div className="container-page py-6">
      <h1 className="text-2xl font-extrabold">Quantity calculator</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-600">
        Tell us what you’re doing and the size. We estimate the materials, pick real products and packs from our catalogue, and
        show bulk prices, offers, stock and delivery, ready to add to your cart.
      </p>

      <form onSubmit={onSubmit} className="mt-5 max-w-2xl rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200">
        <label htmlFor="quantity-text" className="label">
          What do you need?
        </label>
        <textarea
          id="quantity-text"
          className="input min-h-20"
          maxLength={500}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={EXAMPLES[0]}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          {EXAMPLES.slice(1).map((example) => (
            <button
              key={example}
              type="button"
              className="rounded-full bg-steel-50 px-3 py-1 text-xs text-ink-700 ring-1 ring-steel-200 hover:bg-steel-100"
              onClick={() => {
                setText(example)
                startNew({ text: example })
              }}
            >
              {example}
            </button>
          ))}
        </div>
        <button type="submit" className="btn-primary mt-4" disabled={!text.trim() || estimate.isPending}>
          Calculate
        </button>
      </form>

      <CalculatorChips calculators={calculators} active={result?.calculator ?? null} onPick={(key) => startNew({ calculator: key, text: '' })} />

      {estimate.isPending && (
        <div className="mt-6">
          <Spinner label="Working it out…" />
        </div>
      )}
      {estimate.isError && !(estimate.error instanceof ApiError && estimate.error.code === 'invalid_answers') && (
        <p role="alert" className="mt-6 text-sm text-danger-600">
          {errorMessage(estimate.error, 'Could not work that out. Please try again.')}
        </p>
      )}

      {result && (
        <div className={estimate.isPending ? 'opacity-60' : ''}>
          <ResultView
            result={result}
            inputs={inputs}
            fieldErrors={fieldErrors}
            onAnswers={(next) => {
              setInputs(next)
              run({ inputs: next })
            }}
            onOverride={(key, change) => {
              const next = { ...overrides, [key]: { ...overrides[key], ...change } }
              setOverrides(next)
              run({ overrides: next })
            }}
            pin={pin}
            onPin={(value) => {
              setPin(value)
              run({ pin: value })
            }}
            coupon={coupon}
            onCoupon={(value) => {
              setCoupon(value)
              run({ coupon: value })
            }}
            onSave={onSave}
            saving={save.isPending}
            saveError={save.isError ? errorMessage(save.error, 'Could not save.') : ''}
          />
        </div>
      )}
    </div>
  )
}

function CalculatorChips({
  calculators,
  active,
  onPick,
}: {
  calculators: QuantityCalculator[]
  active: string | null
  onPick: (key: string) => void
}) {
  if (!calculators.length) return null
  return (
    <section className="mt-5" aria-labelledby="calculators">
      <h2 id="calculators" className="text-sm font-semibold text-ink-700">
        Or choose a calculator
      </h2>
      <div className="mt-2 flex flex-wrap gap-2">
        {calculators.map((calc) => (
          <button
            key={calc.key}
            type="button"
            onClick={() => onPick(calc.key)}
            aria-pressed={active === calc.key}
            className={`rounded-md px-3 py-1.5 text-sm ring-1 ${active === calc.key ? 'bg-amber-100 ring-amber-500' : 'bg-white ring-steel-200 hover:ring-amber-500'}`}
          >
            {calc.name}
          </button>
        ))}
      </div>
    </section>
  )
}

interface ResultProps {
  result: QuantityResult
  inputs: Record<string, AnswerInput>
  fieldErrors: Record<string, string>
  onAnswers: (inputs: Record<string, AnswerInput>) => void
  onOverride: (key: string, change: QuantityOverride) => void
  pin: string
  onPin: (pin: string) => void
  coupon: string
  onCoupon: (coupon: string) => void
  onSave: () => void
  saving: boolean
  saveError: string
}

function ResultView(props: ResultProps) {
  const { result } = props
  const [editing, setEditing] = useState(false)
  if (!result.calculator) {
    return (
      <div role="status" className="mt-6 max-w-2xl rounded-2xl bg-white shadow-(--shadow-card) p-4 text-sm ring-1 ring-steel-200">
        <p>{result.message}</p>
        {result.ai.notice && <p className="mt-2 text-xs text-ink-600">{result.ai.notice}</p>}
      </div>
    )
  }
  const showForm = !result.complete || editing || Object.keys(props.fieldErrors).length > 0
  return (
    <section className="mt-6" aria-labelledby="result-title">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">{result.name}</p>
      <h2 id="result-title" className="text-xl font-extrabold">
        {result.title || result.name}
      </h2>
      <p className="mt-1 max-w-3xl text-sm text-ink-700">{result.summary}</p>
      {result.interpretations && result.interpretations.length > 0 && (
        <ul className="mt-2 text-xs text-ink-600" aria-label="How we read your measurements">
          {result.interpretations.map((note) => (
            <li key={note.key}>Read as: {note.text}</li>
          ))}
        </ul>
      )}
      {result.ai.notice && (
        <p role="status" className="mt-2 max-w-3xl rounded-md bg-amber-50 px-3 py-2 text-xs text-ink-800">
          {result.ai.notice}
        </p>
      )}

      {(result.safety?.length || result.professional || result.verify || result.not_sold) && (
        <div className="mt-4 max-w-3xl space-y-1 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" role="note">
          {result.verify && <p className="font-semibold">{result.verify}</p>}
          {result.professional && <p className="font-semibold">{result.professional}</p>}
          {result.safety?.map((line) => (
            <p key={line}>{line}</p>
          ))}
          {result.not_sold && <p className="text-ink-700">{result.not_sold}</p>}
        </div>
      )}

      {showForm ? (
        <AnswersForm {...props} onDone={() => setEditing(false)} />
      ) : (
        <div className="mt-4 flex max-w-3xl flex-wrap items-start justify-between gap-3 rounded-2xl bg-white shadow-(--shadow-card) p-3 text-sm ring-1 ring-steel-200">
          <ul className="space-y-0.5 text-ink-700" aria-label="Assumptions">
            {result.assumptions?.map((a) => (
              <li key={a.key}>{a.text}</li>
            ))}
            {!result.assumptions?.length && <li>No assumptions: every measurement came from you.</li>}
          </ul>
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={() => setEditing(true)}>
            Edit measurements
          </button>
        </div>
      )}

      {result.kit && result.materials && <KitResult {...props} kit={result.kit} materials={result.materials} />}
    </section>
  )
}

function AnswersForm({ result, inputs, fieldErrors, onAnswers, onDone }: ResultProps & { onDone: () => void }) {
  const questions = result.questions ?? []
  const asked = result.complete ? questions : questions.filter((q) => result.missing?.includes(q.key))
  const [values, setValues] = useState<Record<string, AnswerInput>>(() => {
    const start: Record<string, AnswerInput> = {}
    for (const q of questions) {
      const current = inputs[q.key]?.value ?? result.answers?.[q.key] ?? q.default ?? ''
      start[q.key] = { value: String(current), unit: inputs[q.key]?.unit ?? q.unit }
    }
    return start
  })
  const set = (key: string, change: Partial<AnswerInput>) => setValues((v) => ({ ...v, [key]: { value: '', ...v[key], ...change } }))

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    onAnswers({ ...inputs, ...Object.fromEntries(asked.map((q) => [q.key, values[q.key] ?? { value: '' }])) })
    onDone()
  }

  return (
    <form onSubmit={onSubmit} className="mt-4 max-w-3xl rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200" aria-labelledby="answers-title">
      <h3 id="answers-title" className="font-bold">
        {result.complete ? 'Measurements and assumptions' : 'A few details for the right amounts'}
      </h3>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {asked.map((question) =>
          question.kind === 'choice' ? (
            <fieldset key={question.key}>
              <legend className="label">{question.text}</legend>
              <div className="flex flex-wrap gap-2">
                {question.choices.map((choice) => (
                  <label
                    key={choice.value}
                    className={`cursor-pointer rounded-md px-3 py-1.5 text-sm ring-1 ${values[question.key]?.value === choice.value ? 'bg-amber-100 ring-amber-500' : 'bg-white ring-steel-200'}`}
                  >
                    <input
                      type="radio"
                      className="sr-only"
                      name={question.key}
                      value={choice.value}
                      checked={values[question.key]?.value === choice.value}
                      onChange={() => set(question.key, { value: choice.value })}
                    />
                    {choice.label}
                  </label>
                ))}
              </div>
              {fieldErrors[question.key] && <p className="mt-1 text-xs text-danger-600">{fieldErrors[question.key]}</p>}
            </fieldset>
          ) : (
            <div key={question.key}>
              <label htmlFor={`qa-${question.key}`} className="label">
                {question.text}
              </label>
              <div className="flex items-center gap-2">
                <input
                  id={`qa-${question.key}`}
                  type="number"
                  inputMode="decimal"
                  step="any"
                  className="input"
                  value={values[question.key]?.value ?? ''}
                  onChange={(e) => set(question.key, { value: e.target.value })}
                />
                {question.units.length > 1 ? (
                  <select
                    aria-label={`Unit for ${question.text}`}
                    className="input w-24"
                    value={values[question.key]?.unit ?? question.unit}
                    onChange={(e) => set(question.key, { unit: e.target.value })}
                  >
                    {question.units.map((unit) => (
                      <option key={unit} value={unit}>
                        {unit}
                      </option>
                    ))}
                  </select>
                ) : (
                  question.unit && <span className="text-sm text-ink-600">{question.unit}</span>
                )}
              </div>
              {fieldErrors[question.key] && <p className="mt-1 text-xs text-danger-600">{fieldErrors[question.key]}</p>}
            </div>
          ),
        )}
      </div>
      {!result.complete && result.assumptions && result.assumptions.length > 0 && (
        <ul className="mt-3 text-xs text-ink-600">
          {result.assumptions.map((a) => (
            <li key={a.key}>{a.text}</li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex gap-2">
        <button type="submit" className="btn-primary">
          {result.complete ? 'Recalculate' : 'Calculate'}
        </button>
        {result.complete && (
          <button type="button" className="btn-secondary" onClick={onDone}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}

function KitResult({ kit, materials, onOverride, pin, onPin, coupon, onCoupon, onSave, saving, saveError }: ResultProps & { kit: ProjectKit; materials: QuantityMaterial[] }) {
  const { status } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const addToCart = useAddQuantityToCart()
  const [couponText, setCouponText] = useState(coupon)
  const lines = kit.items.filter((i) => i.included && i.variant && !i.problem).map((i) => ({ variant_id: i.variant!.id, quantity: i.quantity }))
  const problems =
    addToCart.error instanceof ApiError && Array.isArray(addToCart.error.details.items) ? (addToCart.error.details.items as { message: string }[]) : []

  function add() {
    if (status !== 'authenticated') {
      void navigate(`/login?next=${encodeURIComponent('/quantity')}`)
      return
    }
    addToCart.mutate(lines, {
      onSuccess: (added) => toast.show(`Added ${pluralize(added.added_lines, 'item')} to your cart.`, { action: { label: 'View cart', to: '/cart' } }),
    })
  }

  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]">
      <div>
        <h3 className="text-lg font-bold">Estimated materials</h3>
        <div className="mt-3">
          <CompatibilityProblems
            problems={kit.compatibility ?? []}
            replaceLabel="Use this instead"
            onReplace={(problem, option) => {
              const variantId = optionVariant(option)
              if (problem.keys?.[1] !== undefined && variantId) onOverride(String(problem.keys[1]), { variant_id: variantId })
            }}
          />
        </div>
        <ul className="mt-3 space-y-4">
          {materials.map((material) => (
            <MaterialCard key={material.key} material={material} items={kit.items.filter((i) => i.base_key === material.key)} onOverride={onOverride} />
          ))}
        </ul>
      </div>
      <aside className="h-fit space-y-3 rounded-2xl bg-white shadow-(--shadow-card) p-4 ring-1 ring-steel-200 lg:sticky lg:top-20" aria-label="Estimated total">
        <PinForm pin={pin || kit.postal_code} onPin={onPin} id="quantity-pin" />
        <p className={`text-sm ${kit.delivery.available ? 'text-ink-800' : 'text-danger-600'}`}>
          {kit.delivery.checked ? kit.delivery.message : 'Enter your PIN to check delivery.'}
        </p>
        <dl className="space-y-1 text-sm">
          <TotalRow label={`Items (${kit.totals.item_count})`} value={formatPrice(kit.totals.subtotal)} />
          {Number(kit.totals.bulk_savings) > 0 && <TotalRow label="Bulk prices saved" value={`−${formatPrice(kit.totals.bulk_savings)}`} tone="good" />}
          {kit.offers.map((offer) => (
            <TotalRow key={offer.name} label={offer.name} value={`−${formatPrice(offer.discount)}`} tone="good" />
          ))}
          {kit.coupon?.applied && <TotalRow label={`Coupon ${kit.coupon.code}`} value={`−${formatPrice(kit.totals.coupon_discount ?? '0')}`} tone="good" />}
          <TotalRow label="Delivery" value={Number(kit.totals.delivery_fee) > 0 ? formatPrice(kit.totals.delivery_fee) : 'Free'} />
          <div className="flex justify-between border-t border-steel-100 pt-2 text-base font-bold">
            <dt>Estimated total</dt>
            <dd>{formatPrice(kit.totals.grand_total)}</dd>
          </div>
        </dl>
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            onCoupon(couponText.trim())
          }}
        >
          <div className="flex-1">
            <label htmlFor="quantity-coupon" className="label">
              Coupon
            </label>
            <input id="quantity-coupon" className="input" value={couponText} onChange={(e) => setCouponText(e.target.value.toUpperCase())} />
          </div>
          <button type="submit" className="btn-secondary">
            Apply
          </button>
        </form>
        {kit.coupon && !kit.coupon.applied && <p className="text-xs text-danger-600">{kit.coupon.message}</p>}
        <p className="text-xs text-ink-600">Prices include GST. The cart checks every price again.</p>
        {kit.delivery.free_delivery_hint && <p className="text-xs text-ink-700">{kit.delivery.free_delivery_hint}</p>}
        {kit.issues.length > 0 && (
          <ul className="space-y-1 text-xs text-danger-600" aria-label="Problems">
            {kit.issues.map((issue) => (
              <li key={`${issue.code}-${issue.item_id ?? 'kit'}`}>{issue.message}</li>
            ))}
          </ul>
        )}
        {problems.length > 0 && (
          <ul role="alert" className="space-y-1 text-xs text-danger-600">
            {problems.map((p) => (
              <li key={p.message}>{p.message}</li>
            ))}
          </ul>
        )}
        {addToCart.isError && !problems.length && (
          <p role="alert" className="text-xs text-danger-600">
            {errorMessage(addToCart.error, 'Could not add to the cart.')}
          </p>
        )}
        <button type="button" className="btn-primary w-full" disabled={!kit.can_add_to_cart || addToCart.isPending} onClick={add}>
          {addToCart.isPending ? 'Adding…' : `Add all ${pluralize(lines.length, 'item')} to cart`}
        </button>
        <button type="button" className="btn-secondary w-full" onClick={onSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save as a project'}
        </button>
        {saveError && (
          <p role="alert" className="text-xs text-danger-600">
            {saveError}
          </p>
        )}
        {addToCart.isSuccess && (
          <Link to="/cart" className="btn-dark w-full">
            Go to cart
          </Link>
        )}
      </aside>
    </div>
  )
}

function MaterialCard({ material, items, onOverride }: { material: QuantityMaterial; items: KitItem[]; onOverride: ResultProps['onOverride'] }) {
  return (
    <li className="rounded-2xl bg-white shadow-(--shadow-card) p-3 ring-1 ring-steel-200">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-semibold">{material.label}</h4>
        <span className="text-sm">
          {material.is_estimate && <span className="mr-1 rounded bg-steel-100 px-1.5 text-xs text-ink-700">Estimated quantity</span>}
          {material.is_optional && <span className="mr-1 rounded bg-steel-100 px-1.5 text-xs text-ink-700">Optional</span>}
          Need about <strong>{amountText(material.need.amount, material.need.unit_label)}</strong>
        </span>
      </div>
      <Breakdown steps={material.steps} />
      {material.found ? (
        <p className="mt-1 text-xs text-ink-700">
          Recommended: {material.recommended}
          {material.covers !== null && material.extra !== null && material.extra > 0.005 && (
            <> (covers {amountText(material.covers, material.need.unit_label)}; {amountText(material.extra, material.need.unit_label)} extra from rounding up to whole packs)</>
          )}
        </p>
      ) : (
        <p className="mt-1 text-sm text-ink-600">Not found in our catalogue.</p>
      )}
      {material.explanation && <p className="text-xs text-ink-600">{material.explanation}</p>}
      <ul className="mt-2 space-y-2">
        {items
          .filter((item) => item.variant)
          .map((item) => (
            <ItemRow key={item.material_key} item={item} onOverride={onOverride} />
          ))}
      </ul>
    </li>
  )
}

const PROBLEM_TEXT: Record<Exclude<KitItem['problem'], ''>, string> = {
  not_found: 'Not found in our catalogue.',
  unavailable: 'No longer available.',
  too_many: 'More than you can order at once.',
  short_stock: 'Not enough in stock.',
}

function ItemRow({ item, onOverride }: { item: KitItem; onOverride: ResultProps['onOverride'] }) {
  const set = (change: QuantityOverride) => onOverride(item.material_key, change)
  const next = item.price?.next_tier
  return (
    <li className={`flex gap-3 rounded-md p-2 ring-1 ${item.included ? 'ring-steel-200' : 'opacity-75 ring-steel-100'}`}>
      <input
        type="checkbox"
        className="mt-1 size-5 accent-amber-500"
        checked={item.included}
        onChange={(e) => set({ included: e.target.checked })}
        aria-label={`Include ${item.product?.name ?? item.label}`}
      />
      {item.product && (
        <Link to={`/p/${item.product.slug}`} className="shrink-0">
          <ProductImage src={item.product.image} alt={item.product.image_alt || item.product.name} className="size-14 rounded" />
        </Link>
      )}
      <div className="min-w-0 flex-1">
        {item.product && (
          <Link to={`/p/${item.product.slug}`} className="block text-sm font-medium hover:text-amber-700">
            {item.product.name}
            {item.variant?.name && <span className="text-ink-600"> · {item.variant.name}</span>}
          </Link>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <QuantityStepper value={item.quantity} max={9999} onChange={(quantity) => set({ quantity })} label={`Quantity of ${item.product?.name ?? item.label}`} size="sm" />
          {item.price && (
            <span className="text-sm">
              {formatPrice(item.price.unit_price)} each
              {item.price.applied_tier && <span className="ml-1 text-xs text-success-600">bulk price from {item.price.applied_tier.min_quantity}</span>}
            </span>
          )}
          <StockBadge item={item} />
          {item.price && <span className="ml-auto font-semibold">{formatPrice(item.price.line_total)}</span>}
        </div>
        {next && next.reachable !== false && (
          <button type="button" className="mt-1 text-xs text-amber-700 underline" onClick={() => set({ quantity: next.min_quantity })}>
            Add {next.units_more} more to unlock {formatPrice(next.unit_price)}/unit
          </button>
        )}
        {item.problem && <p className="text-xs text-danger-600">{PROBLEM_TEXT[item.problem]}</p>}
        {item.alternatives.length > 0 && (
          <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-ink-600">Change product</summary>
            <ul className="mt-1 space-y-1">
              {item.alternatives.map((alt) => (
                <li key={alt.id} className="flex items-center justify-between gap-2">
                  <span>
                    {alt.name} · {formatPrice(alt.price)}
                  </span>
                  <button
                    type="button"
                    className="text-amber-700 underline"
                    disabled={!(alt.variant_id ?? alt.default_variant_id)}
                    onClick={() => set({ variant_id: (alt.variant_id ?? alt.default_variant_id)! })}
                  >
                    Use this
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </li>
  )
}
