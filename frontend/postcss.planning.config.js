import tailwind from 'tailwindcss'
import autoprefixer from 'autoprefixer'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))

export default {
  plugins: [tailwind({ config: resolve(here, 'tailwind.planning.config.js') }), autoprefixer()],
}
