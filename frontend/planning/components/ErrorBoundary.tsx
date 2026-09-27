import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface Props {
  children: ReactNode
  /** Changing this resets the boundary, so navigating away from a broken page recovers. */
  resetKey?: string
}

interface State {
  error: Error | null
}

/**
 * Keeps one bad page from blanking the whole dashboard.
 *
 * A render error in a chart or a table shows here with its message instead of an empty
 * screen, which is the difference between "this panel is broken" and "the service is
 * down" — and the sidebar stays usable either way.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidUpdate(prev: Props): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('dashboard render failed', error, info.componentStack)
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle size={20} className="text-amber-600 mt-0.5 shrink-0" />
          <div>
            <h2 className="text-sm font-semibold text-amber-900">This page could not be rendered</h2>
            <p className="text-sm text-amber-800 mt-1">{error.message}</p>
            <p className="text-xs text-amber-700 mt-3">
              The rest of the dashboard still works — pick another page in the sidebar. The full stack trace
              is in the browser console.
            </p>
            <button
              onClick={() => this.setState({ error: null })}
              className="mt-4 rounded-lg bg-white border border-amber-300 px-3 py-1.5 text-xs text-amber-900 hover:border-amber-500"
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    )
  }
}
