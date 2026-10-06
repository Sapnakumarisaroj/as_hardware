import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ErrorState, PageSpinner, SignInPrompt, Spinner } from '@/components/feedback'
import { TrashIcon } from '@/components/icons'
import { QuantityStepper } from '@/components/QuantityStepper'
import { useToast } from '@/components/toast'
import { useAuth } from '@/features/auth/context'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { usePincode } from '@/features/delivery/location'
import {
  useAddProjectToCart,
  useAnswerProject,
  useChangeItem,
  useDeleteProject,
  useProject,
  useProjects,
  useProjectTypes,
  useRemoveItem,
  useResetProject,
  useStartProject,
} from '@/features/projects/api'
import { optionVariant } from '@/features/compatibility/api'
import { CompatibilityProblems } from '@/features/compatibility/components'
import { Breakdown, PinForm, StockBadge, TotalRow } from '@/features/projects/components'
import type { AnswerValue, KitItem, ProjectKit, ProjectPlan, ProjectQuestion, ProjectStatus } from '@/features/projects/types'
import { ApiError } from '@/lib/api/errors'
import { formatDate, formatPrice, pluralize } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const EXAMPLES = [
  'Paint my 12x15 bedroom, the walls have a few cracks',
  'Install 2 shelves on a concrete wall, I don’t have a drill',
  'Waterproofing for a 300 sq ft terrace',
  'मेरे 10x12 कमरे की पुताई करनी है',
]

const STATUS_LABEL: Record<ProjectStatus, string> = {
  draft: 'Needs details',
  ready: 'Kit ready',
  ordered: 'Added to cart',
  archived: 'Archived',
}

const UNIT_LABEL: Record<string, string> = { l: 'L', kg: 'kg', m: 'm', pcs: 'pcs' }

function amountText(amount: number | null, unit: string): string {
  if (amount === null) return ''
  const shown = amount >= 10 ? Math.round(amount).toString() : Number(amount.toFixed(1)).toString()
  return `${shown} ${UNIT_LABEL[unit] ?? unit}`
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

// --- /projects ----------------------------------------------------------------------------------------

export function ProjectsPage() {
  usePageMeta('Project builder', 'Describe a home job and get a kit of the materials, priced and checked for delivery.')
  const { status } = useAuth()
  const navigate = useNavigate()
  const types = useProjectTypes()
  const start = useStartProject()
  const [description, setDescription] = useState('')
  const signedIn = status === 'authenticated'

  function begin(input: { description?: string; project_type?: string }) {
    if (!signedIn) {
      void navigate(`/login?next=${encodeURIComponent('/projects')}`)
      return
    }
    start.mutate(input, { onSuccess: (plan) => void navigate(`/projects/${plan.id}`) })
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (description.trim()) begin({ description: description.trim() })
  }

  return (
    <div className="container-page py-6">
      <h1 className="text-2xl font-extrabold">Project builder</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-600">
        Tell us the job. We ask only what changes the materials, then build a kit from our catalogue with bulk prices, offers,
        stock and delivery checked, ready to add to your cart in one go.
      </p>

      <form onSubmit={onSubmit} className="mt-5 max-w-2xl rounded-lg bg-white p-4 ring-1 ring-steel-200">
        <label htmlFor="project-description" className="label">
          What are you working on?
        </label>
        <textarea
          id="project-description"
          className="input min-h-24"
          maxLength={500}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={EXAMPLES[0]}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          {EXAMPLES.slice(1).map((example) => (
            <button key={example} type="button" className="rounded-full bg-steel-50 px-3 py-1 text-xs text-ink-700 ring-1 ring-steel-200 hover:bg-steel-100" onClick={() => setDescription(example)}>
              {example}
            </button>
          ))}
        </div>
        {start.isError && (
          <p role="alert" className="mt-3 text-sm text-danger-600">
            {errorMessage(start.error, 'Could not start the project.')}
          </p>
        )}
        <button type="submit" className="btn-primary mt-4" disabled={!description.trim() || start.isPending}>
          {start.isPending ? 'Working it out…' : signedIn ? 'Plan my project' : 'Sign in to plan'}
        </button>
      </form>

      <section className="mt-8" aria-labelledby="project-types">
        <h2 id="project-types" className="text-lg font-bold">
          Or pick a job
        </h2>
        {types.isLoading && <Spinner />}
        {types.data && (
          <ul className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {types.data.map((type) => (
              <li key={type.key}>
                <button
                  type="button"
                  onClick={() => begin({ project_type: type.key })}
                  disabled={start.isPending}
                  className="h-full w-full rounded-lg bg-white p-4 text-left ring-1 ring-steel-200 hover:ring-amber-500"
                >
                  <span className="font-semibold text-ink-900">{type.name}</span>
                  <span className="mt-1 block text-xs text-ink-600">{type.summary}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {signedIn && <MyProjects />}
    </div>
  )
}

function MyProjects() {
  const projects = useProjects()
  const remove = useDeleteProject()
  if (projects.isLoading) return <Spinner />
  if (!projects.data?.results.length) return null
  return (
    <section className="mt-8" aria-labelledby="my-projects">
      <h2 id="my-projects" className="text-lg font-bold">
        Your projects
      </h2>
      <ul className="mt-3 divide-y divide-steel-100 rounded-lg bg-white ring-1 ring-steel-200">
        {projects.data.results.map((project) => (
          <li key={project.id} className="flex items-center gap-3 p-3">
            <Link to={`/projects/${project.id}`} className="min-w-0 flex-1 hover:text-amber-600">
              <span className="block truncate font-semibold">{project.title}</span>
              <span className="text-xs text-ink-600">
                {STATUS_LABEL[project.status]} · {pluralize(project.item_count, 'item')} · {formatDate(project.updated_at)}
              </span>
            </Link>
            <button
              type="button"
              className="rounded p-2 text-ink-600 hover:bg-steel-50"
              aria-label={`Delete ${project.title}`}
              onClick={() => remove.mutate(project.id)}
            >
              <TrashIcon className="size-4" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

// --- /projects/:id ------------------------------------------------------------------------------------

export function ProjectPage() {
  const { id: rawId } = useParams()
  const id = Number(rawId)
  const { status } = useAuth()
  const savedPin = usePincode()
  const [pin, setPin] = useState(savedPin)
  const plan = useProject(id, pin)
  usePageMeta(plan.data?.title ?? 'Project')

  if (status !== 'authenticated') {
    return (
      <div className="container-page py-6">
        <SignInPrompt message="Sign in to see your project." next={`/projects/${rawId ?? ''}`} />
      </div>
    )
  }
  if (plan.isLoading) return <PageSpinner />
  if (plan.isError || !plan.data) {
    return (
      <div className="container-page py-6">
        <ErrorState error={plan.error} onRetry={() => void plan.refetch()} title="Could not load the project" />
      </div>
    )
  }
  return <ProjectView plan={plan.data} pin={pin} onPin={setPin} />
}

function ProjectView({ plan, pin, onPin }: { plan: ProjectPlan; pin: string; onPin: (pin: string) => void }) {
  const [editing, setEditing] = useState(false)
  return (
    <div className="container-page py-6">
      <Link to="/projects" className="text-sm text-ink-600 hover:text-amber-600">
        ← All projects
      </Link>
      <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-amber-700">{plan.type_name}</p>
      <h1 className="text-2xl font-extrabold">{plan.title}</h1>
      {plan.description && <p className="mt-1 text-sm text-ink-600">“{plan.description}”</p>}
      <p className="mt-2 max-w-3xl text-sm text-ink-800">{plan.summary}</p>

      <SafetyNotes plan={plan} />

      {(!plan.complete || editing) && <QuestionsForm plan={plan} pin={pin} onDone={() => setEditing(false)} />}
      {plan.complete && !editing && (
        <AnswersSummary plan={plan} onEdit={() => setEditing(true)} />
      )}

      {plan.kit && <KitView plan={plan} kit={plan.kit} pin={pin} onPin={onPin} />}
    </div>
  )
}

function SafetyNotes({ plan }: { plan: ProjectPlan }) {
  if (!plan.safety.length && !plan.professional && !plan.not_sold && !plan.verify) return null
  return (
    <div className="mt-4 max-w-3xl space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-ink-900" role="note">
      {plan.professional && <p className="font-semibold">{plan.professional}</p>}
      {plan.verify && <p className="font-semibold">{plan.verify}</p>}
      {plan.safety.map((line) => (
        <p key={line}>{line}</p>
      ))}
      {plan.not_sold && <p className="text-ink-700">{plan.not_sold}</p>}
    </div>
  )
}

function answerText(question: ProjectQuestion, value: AnswerValue | undefined): string {
  if (value === undefined) return '—'
  const choice = question.choices.find((c) => c.value === value)
  return choice ? choice.label : `${value} ${question.unit}`.trim()
}

function AnswersSummary({ plan, onEdit }: { plan: ProjectPlan; onEdit: () => void }) {
  const assumed = new Set(plan.assumptions.map((a) => a.key))
  return (
    <section className="mt-5 max-w-3xl rounded-lg bg-white p-4 ring-1 ring-steel-200" aria-labelledby="answers">
      <div className="flex items-center justify-between gap-3">
        <h2 id="answers" className="font-bold">
          Your answers
        </h2>
        <button type="button" className="btn-secondary px-3 py-1.5" onClick={onEdit}>
          Change answers
        </button>
      </div>
      {plan.interpretations && plan.interpretations.length > 0 && (
        <ul className="mt-1 text-xs text-ink-600" aria-label="How we read your measurements">
          {plan.interpretations.map((note) => (
            <li key={note.key}>{note.text}</li>
          ))}
        </ul>
      )}
      <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {plan.questions.map((question) => (
          <div key={question.key} className="flex justify-between gap-3">
            <dt className="text-ink-600">{question.text}</dt>
            <dd className="font-medium">
              {answerText(question, plan.answers[question.key] ?? (assumed.has(question.key) ? (question.default ?? undefined) : undefined))}
              {assumed.has(question.key) && <span className="ml-1 text-xs text-ink-600">(assumed)</span>}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function QuestionsForm({ plan, pin, onDone }: { plan: ProjectPlan; pin: string; onDone: () => void }) {
  const answer = useAnswerProject(plan.id, pin)
  const asked = plan.complete ? plan.questions : plan.questions.filter((q) => plan.missing.includes(q.key))
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(plan.questions.map((q) => [q.key, String(plan.answers[q.key] ?? q.default ?? '')])),
  )
  const fieldErrors = answer.error instanceof ApiError && answer.error.code === 'invalid_answers' ? (answer.error.details as Record<string, string>) : {}

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const answers: Record<string, AnswerValue> = {}
    for (const question of asked) {
      const raw = values[question.key]?.trim() ?? ''
      if (raw === '') continue
      answers[question.key] = question.kind === 'number' ? Number(raw) : raw
    }
    answer.mutate({ answers }, { onSuccess: onDone })
  }

  return (
    <form onSubmit={onSubmit} className="mt-5 max-w-3xl rounded-lg bg-white p-4 ring-1 ring-steel-200" aria-labelledby="questions">
      <h2 id="questions" className="font-bold">
        {plan.complete ? 'Change your answers' : 'A few details for the right amounts'}
      </h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {asked.map((question) =>
          question.kind === 'choice' ? (
            <fieldset key={question.key}>
              <legend className="label">{question.text}</legend>
              <div className="flex flex-wrap gap-2">
                {question.choices.map((choice) => (
                  <label
                    key={choice.value}
                    className={`cursor-pointer rounded-md px-3 py-1.5 text-sm ring-1 ${values[question.key] === choice.value ? 'bg-amber-100 ring-amber-500' : 'bg-white ring-steel-200'}`}
                  >
                    <input
                      type="radio"
                      className="sr-only"
                      name={question.key}
                      value={choice.value}
                      checked={values[question.key] === choice.value}
                      onChange={() => setValues((v) => ({ ...v, [question.key]: choice.value }))}
                    />
                    {choice.label}
                  </label>
                ))}
              </div>
              {fieldErrors[question.key] && <p className="mt-1 text-xs text-danger-600">{fieldErrors[question.key]}</p>}
            </fieldset>
          ) : (
            <div key={question.key}>
              <label htmlFor={`q-${question.key}`} className="label">
                {question.text}
              </label>
              <div className="flex items-center gap-2">
                <input
                  id={`q-${question.key}`}
                  type="number"
                  inputMode="decimal"
                  className="input"
                  min={question.min}
                  max={question.max}
                  step="any"
                  value={values[question.key] ?? ''}
                  onChange={(e) => setValues((v) => ({ ...v, [question.key]: e.target.value }))}
                />
                {question.unit && <span className="text-sm text-ink-600">{question.unit}</span>}
              </div>
              {fieldErrors[question.key] && <p className="mt-1 text-xs text-danger-600">{fieldErrors[question.key]}</p>}
            </div>
          ),
        )}
      </div>
      {plan.assumptions.length > 0 && !plan.complete && (
        <ul className="mt-3 text-xs text-ink-600">
          {plan.assumptions.map((a) => (
            <li key={a.key}>{a.text}</li>
          ))}
        </ul>
      )}
      {answer.isError && !Object.keys(fieldErrors).length && (
        <p role="alert" className="mt-3 text-sm text-danger-600">
          {errorMessage(answer.error, 'Could not save your answers.')}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <button type="submit" className="btn-primary" disabled={answer.isPending}>
          {answer.isPending ? 'Working out the kit…' : plan.complete ? 'Update the kit' : 'Build my kit'}
        </button>
        {plan.complete && (
          <button type="button" className="btn-secondary" onClick={onDone}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}

// --- The kit ------------------------------------------------------------------------------------------

function KitView({ plan, kit, pin, onPin }: { plan: ProjectPlan; kit: ProjectKit; pin: string; onPin: (pin: string) => void }) {
  const toast = useToast()
  const addToCart = useAddProjectToCart(plan.id, pin)
  const reset = useResetProject(plan.id, pin)
  const change = useChangeItem(plan.id, pin)
  const problems =
    addToCart.error instanceof ApiError && Array.isArray(addToCart.error.details.items)
      ? (addToCart.error.details.items as { message: string }[])
      : []

  function add() {
    addToCart.mutate(undefined, {
      onSuccess: (result) =>
        toast.show(`Added ${pluralize(result.added?.added_lines ?? kit.included_count, 'item')} to your cart.`, {
          action: { label: 'View cart', to: '/cart' },
        }),
    })
  }

  return (
    <section className="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]" aria-labelledby="kit">
      <div>
        <div className="flex flex-wrap items-end justify-between gap-2">
          <h2 id="kit" className="text-lg font-bold">
            Your kit
          </h2>
          <button type="button" className="text-sm text-ink-600 underline hover:text-amber-600" onClick={() => reset.mutate()} disabled={reset.isPending}>
            Back to the suggestions
          </button>
        </div>
        <p className="mt-1 text-xs text-ink-600">{plan.estimate_notice}</p>
        <div className="mt-3">
          <CompatibilityProblems
            problems={kit.compatibility ?? []}
            replaceLabel="Use this instead"
            onReplace={(problem, option) => {
              const itemId = Number(problem.keys?.[1])
              const variantId = optionVariant(option)
              if (itemId && variantId) change.mutate({ itemId, variant_id: variantId })
            }}
          />
        </div>
        <ul className="mt-3 space-y-3">
          {kit.items.map((item) => (
            <KitItemRow key={item.id} projectId={plan.id} item={item} pin={pin} />
          ))}
        </ul>
      </div>

      <aside className="h-fit space-y-3 rounded-lg bg-white p-4 ring-1 ring-steel-200 lg:sticky lg:top-20" aria-label="Kit total">
        <PinForm pin={pin || kit.postal_code} onPin={onPin} />
        <p className={`text-sm ${kit.delivery.available ? 'text-ink-800' : 'text-danger-600'}`}>{kit.delivery.message}</p>
        <dl className="space-y-1 text-sm">
          <TotalRow label={`Items (${kit.totals.item_count})`} value={formatPrice(kit.totals.subtotal)} />
          {Number(kit.totals.bulk_savings) > 0 && <TotalRow label="Bulk prices saved" value={`−${formatPrice(kit.totals.bulk_savings)}`} tone="good" />}
          {kit.offers.map((offer) => (
            <TotalRow key={offer.name} label={offer.name} value={`−${formatPrice(offer.discount)}`} tone="good" />
          ))}
          <TotalRow label="Delivery" value={Number(kit.totals.delivery_fee) > 0 ? formatPrice(kit.totals.delivery_fee) : 'Free'} />
          <div className="flex justify-between border-t border-steel-100 pt-2 text-base font-bold">
            <dt>Total</dt>
            <dd>{formatPrice(kit.totals.grand_total)}</dd>
          </div>
        </dl>
        <p className="text-xs text-ink-600">Prices include GST. Your cart checks every price again.</p>
        {kit.delivery.free_delivery_hint && <p className="text-xs text-ink-700">{kit.delivery.free_delivery_hint}</p>}
        {kit.offers_in_reach.map((offer) => (
          <p key={offer.name} className="text-xs text-ink-700">
            {offer.name}: spend {formatPrice(offer.min_order_value)} or more.
          </p>
        ))}
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
            {errorMessage(addToCart.error, 'Could not add the kit.')}
          </p>
        )}
        <button type="button" className="btn-primary w-full" disabled={!kit.can_add_to_cart || addToCart.isPending} onClick={add}>
          {addToCart.isPending ? 'Adding…' : `Add ${pluralize(kit.included_count, 'item')} to cart`}
        </button>
        {plan.status === 'ordered' && (
          <Link to="/cart" className="btn-secondary w-full">
            Go to cart
          </Link>
        )}
      </aside>
    </section>
  )
}

const PROBLEM_TEXT: Record<Exclude<KitItem['problem'], ''>, string> = {
  not_found: 'Not found in our catalogue.',
  unavailable: 'No longer available.',
  too_many: 'More than you can order at once.',
  short_stock: 'Not enough in stock.',
}

function KitItemRow({ projectId, item, pin }: { projectId: number; item: KitItem; pin: string }) {
  const change = useChangeItem(projectId, pin)
  const remove = useRemoveItem(projectId, pin)
  const busy = change.isPending || remove.isPending
  const set = (vars: { variant_id?: number; quantity?: number; included?: boolean }) => change.mutate({ itemId: Number(item.id), ...vars })
  const suggestion =
    item.customer_set && item.suggested.variant_id && (item.suggested.variant_id !== item.variant?.id || item.suggested.quantity !== item.quantity)
  const nextTier = item.price?.next_tier

  return (
    <li className={`rounded-lg bg-white p-3 ring-1 ${item.included ? 'ring-steel-200' : 'opacity-75 ring-steel-100'}`}>
      <div className="flex gap-3">
        <input
          type="checkbox"
          className="mt-1 size-5 accent-amber-500"
          checked={item.included}
          disabled={busy || !item.variant}
          onChange={(e) => set({ included: e.target.checked })}
          aria-label={`Include ${item.label}`}
        />
        {item.product && (
          <Link to={`/p/${item.product.slug}`} className="shrink-0">
            <ProductImage src={item.product.image} alt={item.product.image_alt || item.product.name} className="size-16 rounded" />
          </Link>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold">{item.label}</span>
            {item.is_estimate && <span className="rounded bg-steel-100 px-1.5 text-xs text-ink-700">Estimate</span>}
            {item.is_optional && <span className="rounded bg-steel-100 px-1.5 text-xs text-ink-700">Optional</span>}
            {item.added_by_customer && <span className="rounded bg-amber-100 px-1.5 text-xs">Added by you</span>}
            {item.customer_set && !item.added_by_customer && <span className="rounded bg-amber-100 px-1.5 text-xs">Changed by you</span>}
          </div>
          {item.product ? (
            <Link to={`/p/${item.product.slug}`} className="block text-sm text-ink-800 hover:text-amber-600">
              {item.product.name}
              {item.variant?.name && <span className="text-ink-600"> · {item.variant.name}</span>}
            </Link>
          ) : (
            <p className="text-sm text-ink-600">{PROBLEM_TEXT.not_found}</p>
          )}
          {item.rationale && <p className="mt-0.5 text-xs text-ink-600">{item.rationale}</p>}
          {item.need.amount !== null && item.status === 'found' && (
            <p className="text-xs text-ink-600">
              Need about {amountText(item.need.amount, item.need.unit)}
              {item.pack_amount && item.need.unit !== 'pcs' ? ` · ${amountText(item.pack_amount, item.need.unit)} per pack` : ''}
              {item.note ? ` · ${item.note}` : ''}
            </p>
          )}
          {item.pack_explanation && <p className="text-xs text-ink-600">{item.pack_explanation}</p>}
          <Breakdown steps={item.steps} />
          {!item.size_known && <p className="text-xs text-amber-700">Check the pack size before ordering.</p>}
          {item.problem && item.problem !== 'not_found' && <p className="text-xs text-danger-600">{PROBLEM_TEXT[item.problem]}</p>}
          {suggestion && (
            <button
              type="button"
              className="mt-1 text-xs text-amber-700 underline"
              disabled={busy}
              onClick={() => set({ variant_id: item.suggested.variant_id!, quantity: item.suggested.quantity ?? undefined })}
            >
              Use the suggestion for your answers ({item.suggested.quantity} × pack)
            </button>
          )}

          {item.variant && (
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <QuantityStepper value={item.quantity} max={9999} onChange={(quantity) => set({ quantity })} disabled={busy} label={`Quantity of ${item.label}`} size="sm" />
              {item.price && (
                <span className="text-sm">
                  {formatPrice(item.price.unit_price)} each
                  {item.price.applied_tier && <span className="ml-1 text-xs text-success-600">bulk price from {item.price.applied_tier.min_quantity}</span>}
                </span>
              )}
              <StockBadge item={item} />
              {item.price && <span className="ml-auto font-semibold">{formatPrice(item.price.line_total)}</span>}
            </div>
          )}
          {nextTier && (
            <button type="button" className="mt-1 text-xs text-amber-700 underline" disabled={busy} onClick={() => set({ quantity: nextTier.min_quantity })}>
              Add {nextTier.units_more} more for {formatPrice(nextTier.unit_price)} each
            </button>
          )}
          {item.alternatives.length > 0 && (
            <details className="mt-1 text-xs">
              <summary className="cursor-pointer text-ink-600">Other choices</summary>
              <ul className="mt-1 space-y-1">
                {item.alternatives.map((alt) => (
                  <li key={alt.id} className="flex items-center justify-between gap-2">
                    <span>
                      {alt.name} · {formatPrice(alt.price)}
                    </span>
                    <button
                      type="button"
                      className="text-amber-700 underline"
                      disabled={busy || !(alt.variant_id ?? alt.default_variant_id)}
                      onClick={() => set({ variant_id: (alt.variant_id ?? alt.default_variant_id)! })}
                    >
                      Use this
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {change.isError && (
            <p role="alert" className="mt-1 text-xs text-danger-600">
              {errorMessage(change.error, 'Could not change this item.')}
            </p>
          )}
        </div>
        {item.added_by_customer && (
          <button type="button" className="self-start rounded p-1 text-ink-600 hover:bg-steel-50" aria-label={`Remove ${item.label}`} onClick={() => remove.mutate(Number(item.id))} disabled={busy}>
            <TrashIcon className="size-4" />
          </button>
        )}
      </div>
    </li>
  )
}
