import { SystemStatus } from '@/features/system/SystemStatus'
import { env } from '@/lib/env'

export function HomePage() {
  return (
    <section className="bg-ink-900 text-white">
      <div className="mx-auto max-w-7xl px-4 py-16 sm:py-24">
        <p className="text-sm font-semibold uppercase tracking-widest text-amber-500">
          Hardware · Tools · Electrical · Plumbing
        </p>
        <h1 className="mt-3 max-w-3xl text-4xl font-extrabold leading-tight sm:text-5xl">
          The right part, at your door — fast.
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-steel-200">
          {env.appName} is being built. The catalog, cart and delivery features arrive in the next phases.
        </p>
        <div className="mt-8">
          <SystemStatus />
        </div>
      </div>
    </section>
  )
}
