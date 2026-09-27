// Render-only smoke test: mounts every page once through react-dom/server. It cannot
// exercise data (effects do not run server-side), but it does catch an undefined
// component, a bad import and an invalid element type — the usual causes of a page
// rendering as a blank panel.
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

const ROUTES = [
  '/', '/order-plan', '/inventory', '/spare-parts', '/classification', '/forecast',
  '/unit-sales', '/registrations', '/parc', '/parts', '/catalogues', '/exceptions', '/pipeline',
]

export function smoke(): number {
  let failed = 0
  for (const route of ROUTES) {
    try {
      const html = renderToString(
        <MemoryRouter initialEntries={[route]}>
          <App />
        </MemoryRouter>,
      )
      const ok = html.length > 400
      console.log(`${ok ? 'ok  ' : 'THIN'} ${route.padEnd(16)} ${html.length} bytes`)
      if (!ok) failed += 1
    } catch (e) {
      console.log(`FAIL ${route.padEnd(16)} ${(e as Error).message}`)
      failed += 1
    }
  }
  return failed
}

process.exitCode = smoke()
