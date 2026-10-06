/**
 * The browser's own speech services (free, nothing to install):
 * - listening: the Web Speech API (`SpeechRecognition`, Chrome/Edge/Safari; not Firefox). Chrome sends the
 *   sound to its speech service and gives us the words; the shop only ever receives the words.
 * - recording: `MediaRecorder`, for shops that switched on server recognition (browsers that can't listen);
 * - speaking: `speechSynthesis` with a voice for the language when the device has one.
 */

interface RecognitionAlternative {
  transcript: string
  confidence: number
}
interface RecognitionResult {
  readonly isFinal: boolean
  readonly length: number
  [index: number]: RecognitionAlternative
}
interface RecognitionEvent {
  readonly resultIndex: number
  readonly results: { readonly length: number; [index: number]: RecognitionResult }
}
interface RecognitionErrorEvent {
  readonly error: string
}
export interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  maxAlternatives: number
  onresult: ((event: RecognitionEvent) => void) | null
  onerror: ((event: RecognitionErrorEvent) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}
type RecognitionCtor = new () => Recognition

export function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export function canListen(): boolean {
  return recognitionCtor() !== null
}

export function canRecord(): boolean {
  return typeof window.MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
}

export const LISTEN_ERRORS: Record<string, string> = {
  'not-allowed': 'Microphone access was blocked. Allow the microphone for this site in your browser settings, or type instead.',
  'service-not-allowed': 'Microphone access was blocked. Allow the microphone for this site in your browser settings, or type instead.',
  'no-speech': 'I didn’t hear anything. Tap the microphone and speak again.',
  'audio-capture': 'No microphone was found. Connect one, or type instead.',
  network: 'Your browser’s speech service couldn’t be reached. Check the connection, or type instead.',
  'language-not-supported': 'Your browser can’t listen in this language. Pick another language, or type instead.',
}

export interface ListenHandlers {
  onInterim: (text: string) => void
  onFinal: (text: string, confidence: number | null) => void
  onError: (code: string) => void
  onEnd: () => void
}

/** Listens for one sentence. Returns a function that stops listening. */
export function listenOnce(lang: string, handlers: ListenHandlers): () => void {
  const Ctor = recognitionCtor()
  if (!Ctor) {
    handlers.onError('unsupported')
    handlers.onEnd()
    return () => {}
  }
  const recognition = new Ctor()
  recognition.lang = lang
  recognition.interimResults = true
  recognition.continuous = false
  recognition.maxAlternatives = 1
  let finished = false
  recognition.onresult = (event) => {
    let interim = ''
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i]
      const best = result?.[0]
      if (!result || !best) continue
      if (result.isFinal) {
        finished = true
        handlers.onFinal(best.transcript.trim(), Number.isFinite(best.confidence) ? best.confidence : null)
      } else {
        interim += best.transcript
      }
    }
    if (!finished && interim) handlers.onInterim(interim.trim())
  }
  recognition.onerror = (event) => {
    if (event.error !== 'aborted') handlers.onError(event.error)
  }
  recognition.onend = () => handlers.onEnd()
  try {
    recognition.start()
  } catch {
    handlers.onError('busy')
    handlers.onEnd()
  }
  return () => {
    try {
      recognition.stop()
    } catch {
      // already stopped
    }
  }
}

export interface Recording {
  /** Stops and returns the recording. */
  stop: () => Promise<Blob>
  cancel: () => void
}

/** Records from the microphone (stops by itself after `maxSeconds`). */
export async function startRecording(maxSeconds: number, onAutoStop: () => void): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const preferred = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']
  const mimeType = preferred.find((type) => typeof MediaRecorder.isTypeSupported === 'function' && MediaRecorder.isTypeSupported(type))
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
  const chunks: Blob[] = []
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data)
  }
  const release = () => stream.getTracks().forEach((track) => track.stop())
  const timer = window.setTimeout(onAutoStop, maxSeconds * 1000)
  recorder.start()
  return {
    stop: () =>
      new Promise<Blob>((resolve) => {
        window.clearTimeout(timer)
        recorder.onstop = () => {
          release()
          resolve(new Blob(chunks, { type: recorder.mimeType || mimeType || 'audio/webm' }))
        }
        if (recorder.state !== 'inactive') recorder.stop()
        else resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }))
      }),
    cancel: () => {
      window.clearTimeout(timer)
      if (recorder.state !== 'inactive') recorder.stop()
      release()
    },
  }
}

function voiceFor(lang: string): SpeechSynthesisVoice | null {
  if (typeof window.speechSynthesis === 'undefined') return null
  const voices = window.speechSynthesis.getVoices()
  const base = lang.split('-')[0]
  return (
    voices.find((v) => v.lang.toLowerCase() === lang.toLowerCase()) ??
    voices.find((v) => v.lang.toLowerCase().startsWith(`${base}-`)) ??
    null
  )
}

export function canSpeak(): boolean {
  return typeof window.speechSynthesis !== 'undefined' && typeof window.SpeechSynthesisUtterance !== 'undefined'
}

/** Whether the device has a voice for the language (voices load late on some browsers: false then). */
export function hasVoice(lang: string): boolean {
  return canSpeak() && voiceFor(lang) !== null
}

/** Reads `text` aloud with the browser's voice. Returns false when there's no voice for the language. */
export function speakInBrowser(text: string, lang: string): boolean {
  if (!canSpeak() || !text) return false
  const voice = voiceFor(lang)
  if (!voice && !lang.startsWith('en')) return false // an English voice reading Hindi is not useful
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = lang
  if (voice) utterance.voice = voice
  utterance.rate = 1
  window.speechSynthesis.speak(utterance)
  return true
}

export function stopSpeaking() {
  if (canSpeak()) window.speechSynthesis.cancel()
}
