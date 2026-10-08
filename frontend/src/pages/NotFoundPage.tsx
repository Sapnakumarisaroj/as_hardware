import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-xl px-4 py-24 text-center">
      <p className="text-sm font-semibold text-amber-700">404</p>
      <h1 className="mt-2 text-3xl font-bold">Page not found</h1>
      <p className="mt-3 text-ink-600">The page you’re looking for doesn’t exist or has moved.</p>
      <Link
        to="/"
        className="mt-6 inline-block rounded-md bg-amber-500 px-5 py-2.5 font-semibold text-ink-950 hover:bg-amber-600"
      >
        Go to home
      </Link>
    </div>
  )
}
