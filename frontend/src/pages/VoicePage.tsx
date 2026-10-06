import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

import { ErrorState, Spinner } from '@/components/feedback'
import { MicIcon, SpeakerIcon, TrashIcon } from '@/components/icons'
import { useToast } from '@/components/toast'
import { RecommendationCard } from '@/features/ai/components'
import { useAuth } from '@/features/auth/context'
import { savePendingAction } from '@/features/auth/pendingAction'
import { useAddToCart } from '@/features/cart/api'
import { ProductImage } from '@/features/catalog/components/ProductImage'
import { usePincode } from '@/features/delivery/location'
import { fetchServerSpeech, useDeleteVoiceSession, useTranscribe, useVoiceCommand, useVoiceSessions, useVoiceStatus } from '@/features/voice/api'
import {
  canListen,
  canRecord,
  LISTEN_ERRORS,
  listenOnce,
  speakInBrowser,
  startRecording,
  stopSpeaking,
  type Recording,
} from '@/features/voice/speech'
import type { PendingLine, VoiceLanguage, VoiceLanguageOption, VoiceLine, VoiceResult } from '@/features/voice/types'
import { ApiError } from '@/lib/api/errors'
import { formatDate, formatPrice } from '@/lib/format'
import { usePageMeta } from '@/lib/usePageMeta'

const LANGUAGE_KEY = 'boltrun.voice-language'
const SPEAK_KEY = 'boltrun.voice-speak'

const ENGLISH: VoiceLanguageOption = { code: 'en', label: 'English', speech: 'en-IN', voice: 'en-IN' }
const FALLBACK_LANGUAGES: VoiceLanguageOption[] = [
  ENGLISH,
  { code: 'hi', label: 'हिन्दी', speech: 'hi-IN', voice: 'hi-IN' },
  { code: 'hinglish', label: 'Hinglish', speech: 'hi-IN', voice: 'en-IN' },
]

const NO_SPEECH = LISTEN_ERRORS['no-speech'] ?? 'I didn’t hear anything.'
const BLOCKED = LISTEN_ERRORS['not-allowed'] ?? 'Microphone access was blocked.'

type Phase = 'idle' | 'listening' | 'recording' | 'transcribing'

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function store(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // a private window: the choice lasts for this visit only
  }
}

function isLanguage(value: string | null): value is VoiceLanguage {
  return value === 'en' || value === 'hi' || value === 'hinglish'
}

function toPending(lines: VoiceLine[]): PendingLine[] {
  return lines
    .filter((line) => line.status === 'ready' && line.product_id !== null && line.variant_id !== null && line.quantity !== null)
    .map((line) => ({ product_id: line.product_id!, variant_id: line.variant_id!, quantity: line.quantity!, name: line.product_name }))
}

const STATUS_TONE: Record<VoiceLine['status'], string> = {
  ready: '',
  not_found: 'bg-steel-100 text-ink-800',
  too_many: 'bg-amber-100 text-ink-900',
  short_stock: 'bg-amber-100 text-ink-900',
  unavailable: 'bg-steel-100 text-ink-800',
  whole_number: 'bg-amber-100 text-ink-900',
}

function LineCard({
  line,
  busy,
  onAdd,
  onQuantity,
}: {
  line: VoiceLine
  busy: boolean
  onAdd: (line: VoiceLine) => void
  onQuantity: (line: VoiceLine, quantity: number) => void
}) {
  const product = line.product
  const quote = line.quote
  const href = product ? `/p/${product.slug}` : null
  return (
    <li className="rounded-lg bg-white p-3 ring-1 ring-steel-200" data-testid="voice-line">
      <div className="flex gap-3">
        {product && href && (
          <Link to={href} tabIndex={-1} aria-hidden="true" className="shrink-0">
            <ProductImage src={product.image} alt={product.image_alt} className="size-20 rounded" />
          </Link>
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-xs text-ink-600">Heard: “{line.heard}”</p>
          {product && href ? (
            <h3 className="text-sm font-semibold leading-snug">
              <Link to={href} className="hover:text-amber-600">
                {product.name}
              </Link>
            </h3>
          ) : (
            line.product_name && <h3 className="text-sm font-semibold">{line.product_name}</h3>
          )}
          {line.filters.length > 0 && (
            <p className="text-xs text-ink-600">Understood: {line.filters.map((f) => f.label).join(' · ')}</p>
          )}
          {quote && line.status === 'ready' && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm">
              <dt className="text-ink-600">Quantity</dt>
              <dd className="font-semibold">{line.quantity}</dd>
              <dt className="text-ink-600">Price each</dt>
              <dd>
                <span className="font-semibold">{formatPrice(quote.unit_price)}</span>
                {quote.applied_tier && (
                  <span className="ml-2 rounded bg-success-600/10 px-1.5 py-0.5 text-xs font-semibold text-success-600">
                    Bulk price from {quote.applied_tier.min_quantity}
                  </span>
                )}
                {quote.unit_price !== quote.base_unit_price && (
                  <span className="ml-2 text-xs text-ink-600 line-through">{formatPrice(quote.base_unit_price)}</span>
                )}
              </dd>
              {Number(quote.offer_discount) > 0 && (
                <>
                  <dt className="text-ink-600">Offer</dt>
                  <dd className="text-success-600">
                    −{formatPrice(quote.offer_discount)} {quote.offers.map((o) => o.name).join(', ')}
                  </dd>
                </>
              )}
              <dt className="text-ink-600">Total</dt>
              <dd className="font-bold" data-testid="voice-line-total">
                {formatPrice(quote.total)}
              </dd>
            </dl>
          )}
          {line.status !== 'ready' && (
            <p className={`rounded px-2 py-1 text-sm ${STATUS_TONE[line.status]}`} role="note">
              {line.message}
            </p>
          )}
          {line.note && <p className="text-xs text-ink-600">{line.note}</p>}
          {quote?.next_tier?.reachable && line.status === 'ready' && (
            <button
              type="button"
              className="text-left text-sm font-semibold text-amber-600 hover:underline"
              disabled={busy}
              onClick={() => onQuantity(line, quote.next_tier!.min_quantity)}
            >
              Add {quote.next_tier.units_more} more for {formatPrice(quote.next_tier.unit_price)} each (make it {quote.next_tier.min_quantity})
            </button>
          )}
          {line.status === 'ready' && (
            <div className="pt-1">
              <button type="button" className="btn-primary px-3 py-1.5" disabled={busy} onClick={() => onAdd(line)}>
                Add {line.quantity} to cart
              </button>
            </div>
          )}
          {line.alternatives.length > 0 && (
            <p className="text-xs text-ink-600">
              {line.status === 'ready' ? 'Not this one? ' : 'Similar: '}
              {line.alternatives.map((alt, index) => (
                <span key={alt.id}>
                  {index > 0 && ' · '}
                  <Link to={`/p/${alt.slug}`} className="font-semibold text-amber-600 hover:underline">
                    {alt.name}
                  </Link>
                </span>
              ))}
            </p>
          )}
        </div>
      </div>
    </li>
  )
}

function ResultView({
  result,
  busy,
  onAdd,
  onAddAll,
  onCancel,
  onQuantity,
}: {
  result: VoiceResult
  busy: boolean
  onAdd: (line: VoiceLine) => void
  onAddAll: () => void
  onCancel: () => void
  onQuantity: (line: VoiceLine, quantity: number) => void
}) {
  const ready = result.lines.filter((line) => line.status === 'ready')
  const proposing = result.needs_confirmation && ready.length > 0
  return (
    <section aria-labelledby="voice-result-heading" className="space-y-4">
      <div className="space-y-2 rounded-lg bg-white p-4 ring-1 ring-steel-200">
        <h2 id="voice-result-heading" className="text-xs font-semibold uppercase tracking-wide text-ink-600">
          You said
        </h2>
        <p className="text-lg font-semibold" data-testid="voice-transcript">
          “{result.transcript}”
        </p>
        <div className="space-y-2 text-sm text-ink-800" data-testid="voice-reply">
          {result.reply
            .split(/\n{2,}/)
            .filter(Boolean)
            .map((paragraph, index) => (
              <p key={index} className="whitespace-pre-wrap">
                {paragraph}
              </p>
            ))}
        </div>
        {result.notice && (
          <p className="rounded-md bg-amber-100 px-3 py-2 text-sm text-ink-900" role="note">
            {result.notice}
          </p>
        )}
        {result.questions.length > 0 && (
          <ul className="list-inside list-disc text-sm text-ink-800">
            {result.questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        )}
      </div>

      {result.lines.length > 0 && (
        <div className="space-y-2">
          <ul className="space-y-3" aria-label="Items from what you said">
            {result.lines.map((line, index) => (
              <LineCard key={`${line.product_id ?? 'none'}-${index}`} line={line} busy={busy} onAdd={onAdd} onQuantity={onQuantity} />
            ))}
          </ul>
          {proposing && (
            <div className="flex flex-wrap gap-2">
              {ready.length > 1 && (
                <button type="button" className="btn-dark" disabled={busy} onClick={onAddAll}>
                  Add all {ready.length} to cart
                </button>
              )}
              <button type="button" className="btn-secondary" disabled={busy} onClick={onCancel}>
                Cancel
              </button>
            </div>
          )}
          <p className="text-xs text-ink-600">Prices come from our pricing engine; the cart and checkout confirm them again.</p>
        </div>
      )}

      {result.quantity && (
        <Link to={result.quantity.path} className="inline-block text-sm font-semibold text-amber-600 hover:underline">
          Open the quantity calculator: {result.quantity.title}
        </Link>
      )}

      {result.products.length > 0 && (
        <div>
          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Products">
            {result.products.map((product) => (
              <RecommendationCard key={product.id} product={product} />
            ))}
          </ul>
          {result.search_path && (
            <Link to={result.search_path} className="mt-2 inline-block text-sm font-semibold text-amber-600 hover:underline">
              See all results
            </Link>
          )}
        </div>
      )}
    </section>
  )
}

function History() {
  const sessions = useVoiceSessions()
  const remove = useDeleteVoiceSession()
  const rows = sessions.data?.results ?? []
  if (rows.length === 0) return null
  return (
    <section aria-labelledby="voice-history-heading" className="rounded-lg bg-white p-4 ring-1 ring-steel-200">
      <div className="mb-2 flex items-center justify-between">
        <h2 id="voice-history-heading" className="text-base font-bold">
          Your recent voice sessions
        </h2>
        <button type="button" className="text-sm text-danger-600 hover:underline" disabled={remove.isPending} onClick={() => remove.mutate('all')}>
          Clear all
        </button>
      </div>
      <ul className="divide-y divide-steel-100 text-sm">
        {rows.map((row) => (
          <li key={row.id} className="flex items-center justify-between gap-2 py-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate font-semibold">{row.title || 'Voice session'}</span>
              <span className="block text-xs text-ink-600">
                {formatDate(row.updated_at)} · {row.turns} {row.turns === 1 ? 'request' : 'requests'}
              </span>
            </span>
            <button
              type="button"
              className="p-1 text-ink-600 hover:text-danger-600"
              aria-label={`Delete voice session ${row.title}`}
              disabled={remove.isPending}
              onClick={() => remove.mutate(row.id)}
            >
              <TrashIcon className="size-4" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function VoicePage() {
  usePageMeta('Shop by voice', 'Say what you need in English, Hindi or Hinglish, for example “10 bags of cement”.')
  const { status: authStatus } = useAuth()
  const status = useVoiceStatus()
  const command = useVoiceCommand()
  const transcribe = useTranscribe()
  const addToCart = useAddToCart()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const pincode = usePincode()

  const stored = readStored(LANGUAGE_KEY)
  const [language, setLanguage] = useState<VoiceLanguage>(isLanguage(stored) ? stored : 'en')
  const [speakAnswers, setSpeakAnswers] = useState(readStored(SPEAK_KEY) !== 'off')
  const [phase, setPhase] = useState<Phase>('idle')
  const [interim, setInterim] = useState('')
  const [typed, setTyped] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [result, setResult] = useState<VoiceResult | null>(null)
  const [pending, setPendingState] = useState<PendingLine[]>([])
  // Refs too: a recording that stops by itself calls back into handlers created when it started.
  const pendingRef = useRef<PendingLine[]>([])
  const conversationRef = useRef<number | null>(null)
  const stopListening = useRef<(() => void) | null>(null)
  const recording = useRef<Recording | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  const languages = status.data?.languages ?? FALLBACK_LANGUAGES
  const option = languages.find((l) => l.code === language) ?? ENGLISH
  const browserListens = canListen()
  const serverListens = !!status.data?.server_recognition.available && canRecord()
  const busy = command.isPending || addToCart.isPending

  useEffect(
    () => () => {
      stopListening.current?.()
      recording.current?.cancel()
      stopSpeaking()
    },
    [],
  )

  function setPending(update: PendingLine[] | ((current: PendingLine[]) => PendingLine[])) {
    const next = typeof update === 'function' ? update(pendingRef.current) : update
    pendingRef.current = next
    setPendingState(next)
  }

  function chooseLanguage(code: VoiceLanguage) {
    setLanguage(code)
    store(LANGUAGE_KEY, code)
  }

  function toggleSpeaking(on: boolean) {
    setSpeakAnswers(on)
    store(SPEAK_KEY, on ? 'on' : 'off')
    if (!on) stopSpeaking()
  }

  function say(text: string) {
    if (!speakAnswers || !text) return
    if (speakInBrowser(text, option.voice)) return
    if (status.data?.server_voice.available) {
      fetchServerSpeech(text, language)
        .then((blob) => {
          const audio = new Audio(URL.createObjectURL(blob))
          void audio.play().catch(() => undefined)
        })
        .catch(() => undefined) // the answer is on screen anyway
    }
  }

  async function addLines(lines: VoiceLine[]) {
    const items = toPending(lines)
    const first = items[0]
    if (!first) return
    if (authStatus !== 'authenticated') {
      savePendingAction({ type: 'cart', variantId: first.variant_id, quantity: first.quantity, productName: first.name })
      toast.show(
        items.length === 1
          ? 'Sign in to add items to your cart — we’ll add this one for you.'
          : 'Sign in to add items to your cart. We’ll add the first one; say the others again after signing in.',
        { tone: 'info' },
      )
      void navigate(`/login?next=${encodeURIComponent(location.pathname)}`)
      return
    }
    let added = 0
    const addedIds = new Set<number>()
    for (const item of items) {
      try {
        await addToCart.mutateAsync({ variantId: item.variant_id, quantity: item.quantity })
        added += 1
        addedIds.add(item.variant_id)
      } catch (error) {
        toast.show(error instanceof ApiError ? error.message : `Could not add ${item.name}.`, { tone: 'error' })
      }
    }
    setPending((current) => current.filter((p) => !addedIds.has(p.variant_id)))
    if (added > 0) {
      toast.show(added === 1 ? `Added to cart: ${items.find((i) => addedIds.has(i.variant_id))?.name}` : `Added ${added} items to your cart.`, {
        action: { label: 'View cart', to: '/cart' },
      })
    }
  }

  function send(transcript: string, pendingLines: PendingLine[] = pendingRef.current) {
    const text = transcript.trim()
    if (!text) return
    setProblem(null)
    command.mutate(
      { transcript: text, language, conversationId: conversationRef.current, pending: pendingLines, postalCode: pincode || null },
      {
        onSuccess: (answer) => {
          setResult(answer)
          if (answer.conversation_id !== null) conversationRef.current = answer.conversation_id
          if (answer.intent === 'add_to_cart' || answer.intent === 'set_quantity') {
            setPending(toPending(answer.lines))
          } else if (answer.intent === 'confirm') {
            setPending([])
            if (answer.add_now) void addLines(answer.lines)
          } else if (answer.intent !== 'unclear') {
            setPending([])
          }
          say(answer.speech)
          if (answer.navigate) void navigate(answer.navigate.path)
          resultRef.current?.focus()
        },
        onError: (error) => setProblem(error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'),
      },
    )
  }

  async function finishRecording() {
    const current = recording.current
    recording.current = null
    if (!current) return
    setPhase('transcribing')
    const audio = await current.stop()
    transcribe.mutate(
      { audio, language },
      {
        onSuccess: (heard) => {
          setPhase('idle')
          if (heard.empty) setProblem(NO_SPEECH)
          else send(heard.text)
        },
        onError: (error) => {
          setPhase('idle')
          setProblem(error instanceof ApiError ? error.message : 'The recording could not be understood. Please type instead.')
        },
      },
    )
  }

  async function toggleMicrophone() {
    setProblem(null)
    if (phase === 'listening') {
      stopListening.current?.()
      return
    }
    if (phase === 'recording') {
      await finishRecording()
      return
    }
    stopSpeaking()
    if (browserListens) {
      setInterim('')
      setPhase('listening')
      stopListening.current = listenOnce(option.speech, {
        onInterim: setInterim,
        onFinal: (text) => {
          setInterim('')
          send(text)
        },
        onError: (code) => setProblem(LISTEN_ERRORS[code] ?? 'Listening stopped. Tap the microphone to try again, or type instead.'),
        onEnd: () => {
          stopListening.current = null
          setPhase((current) => (current === 'listening' ? 'idle' : current))
        },
      })
      return
    }
    if (serverListens) {
      try {
        recording.current = await startRecording(status.data?.max_audio_seconds ?? 20, () => void finishRecording())
        setPhase('recording')
      } catch {
        setProblem(BLOCKED)
      }
      return
    }
    setProblem('Your browser can’t listen. Type what you need below, or try Chrome, Edge or Safari.')
  }

  function submitTyped(event: FormEvent) {
    event.preventDefault()
    send(typed)
    setTyped('')
  }

  const canUseMicrophone = browserListens || serverListens
  const micLabel =
    phase === 'listening' ? 'Stop listening' : phase === 'recording' ? 'Stop recording' : phase === 'transcribing' ? 'Working…' : 'Start speaking'
  const examples = status.data?.examples[language] ?? []

  return (
    <div className="container-page max-w-3xl space-y-5 py-6">
      <div>
        <h1 className="text-2xl font-extrabold">Shop by voice</h1>
        <p className="text-sm text-ink-600">
          Say what you need, like “10 bags of 53 grade cement”. We show the price for that quantity and add it to your cart only when you say
          “yes” or tap Add.
        </p>
      </div>

      {status.isError && <ErrorState error={status.error} onRetry={() => void status.refetch()} title="Couldn’t open voice shopping" />}

      <fieldset>
        <legend className="mb-1 text-sm font-semibold">Language</legend>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Language">
          {languages.map((l) => (
            <button
              key={l.code}
              type="button"
              role="radio"
              aria-checked={language === l.code}
              onClick={() => chooseLanguage(l.code)}
              className={`rounded-full px-3 py-1.5 text-sm font-semibold ring-1 ${language === l.code ? 'bg-ink-900 text-white ring-ink-900' : 'bg-white text-ink-800 ring-steel-200 hover:ring-amber-500'}`}
            >
              {l.label}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="flex flex-col items-center gap-3 rounded-lg bg-white p-6 text-center ring-1 ring-steel-200">
        <button
          type="button"
          onClick={() => void toggleMicrophone()}
          disabled={phase === 'transcribing' || (!canUseMicrophone && status.isPending)}
          aria-pressed={phase === 'listening' || phase === 'recording'}
          aria-label={micLabel}
          className={`flex size-20 items-center justify-center rounded-full text-ink-950 shadow-md focus-visible:ring-4 focus-visible:ring-amber-300 ${phase === 'listening' || phase === 'recording' ? 'animate-pulse bg-danger-600 text-white' : 'bg-amber-500 hover:bg-amber-600'}`}
        >
          <MicIcon className="size-9" />
        </button>
        <p className="min-h-5 text-sm text-ink-800" role="status" aria-live="polite">
          {phase === 'listening' && (interim ? `“${interim}”` : 'Listening… speak now')}
          {phase === 'recording' && 'Recording… tap again when you’re done'}
          {phase === 'transcribing' && 'Working out what you said…'}
          {phase === 'idle' && command.isPending && 'Finding it in our catalogue…'}
          {phase === 'idle' && !command.isPending && (canUseMicrophone ? 'Tap the microphone and speak' : 'Voice input isn’t available in this browser')}
        </p>
        {pending.length > 0 && phase === 'idle' && !command.isPending && (
          <p className="text-xs text-ink-600">Waiting for your “yes” to add {pending.length === 1 ? pending[0]?.name : `${pending.length} items`}.</p>
        )}
        <label className="flex items-center gap-2 text-sm text-ink-800">
          <input type="checkbox" checked={speakAnswers} onChange={(e) => toggleSpeaking(e.target.checked)} />
          <SpeakerIcon className="size-4" />
          Read answers aloud
        </label>
      </div>

      <form onSubmit={submitTyped} className="flex gap-2" aria-label="Type instead">
        <label htmlFor="voice-typed" className="sr-only">
          Type what you need
        </label>
        <input
          id="voice-typed"
          className="input flex-1"
          placeholder={examples[0] ? `e.g. ${examples[0]}` : 'Type what you need'}
          value={typed}
          maxLength={500}
          onChange={(e) => setTyped(e.target.value)}
        />
        <button type="submit" className="btn-primary" disabled={!typed.trim() || command.isPending}>
          Send
        </button>
      </form>

      {examples.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-ink-600">Try:</span>
          {examples.map((example) => (
            <button
              key={example}
              type="button"
              className="rounded-full bg-steel-100 px-3 py-1 hover:bg-steel-200"
              disabled={command.isPending}
              onClick={() => send(example)}
            >
              {example}
            </button>
          ))}
        </div>
      )}

      {problem && (
        <p className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600" role="alert">
          {problem}
        </p>
      )}

      <div ref={resultRef} tabIndex={-1} className="outline-none" aria-live="polite">
        {command.isPending && !result && <Spinner label="Finding it in our catalogue…" />}
        {result && (
          <ResultView
            result={result}
            busy={busy}
            onAdd={(line) => void addLines([line])}
            onAddAll={() => void addLines(result.lines)}
            onCancel={() => send(language === 'hi' ? 'नहीं' : language === 'hinglish' ? 'nahi' : 'cancel')}
            onQuantity={(line, quantity) =>
              send(String(quantity), toPending([line]))
            }
          />
        )}
      </div>

      <p className="text-xs text-ink-600">
        Your browser’s speech service turns your voice into words (in Chrome that is Google’s service); we receive only the words.
        {status.data?.server_recognition.available && ' When your browser can’t listen, the recording is sent to our server, turned into words and deleted.'}
      </p>

      {authStatus === 'authenticated' ? (
        <History />
      ) : (
        <p className="text-xs text-ink-600">
          <Link to="/login?next=%2Fvoice" className="font-semibold text-amber-600 hover:underline">
            Sign in
          </Link>{' '}
          to add items to your cart and keep a history of what you asked.
        </p>
      )}
    </div>
  )
}
