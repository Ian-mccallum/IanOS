import { mergeConfig } from 'vite'
import { defineConfig } from 'vitest/config'
import viteConfig from './vite.config.js'

// Keep browser-facing lifecycle tests beside the lightweight node:test suite.
// Vite supplies the same JSX transform the dashboard uses in production.
export default mergeConfig(viteConfig, defineConfig({
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: { url: 'http://localhost/' },
    },
    include: ['tests/**/*.ui.test.jsx'],
    setupFiles: ['./tests/setup-ui.js'],
  },
}))
