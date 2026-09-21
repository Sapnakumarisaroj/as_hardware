import { isRouteErrorResponse, Link, useRouteError } from 'react-router'

export function RouteErrorPage() {
  const error = useRouteError()
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : 'Unknown error'
  return (
    <div role="alert" className="mx-auto max-w-xl px-4 py-24 text-center">
      <h1 className="text-3xl font-bold">Something went wrong</h1>
      <p className="mt-3 text-ink-600">{message}</p>
      <Link
        to="/"
        className="mt-6 inline-block rounded-md bg-amber-500 px-5 py-2.5 font-semibold text-ink-950 hover:bg-amber-600"
      >
        Go to home
      </Link>
    </div>
  )
}
