import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { installNavFlush } from './lib/viewport.js'
import './styles.css'

createRoot(document.getElementById('root')).render(<App />)

// WebKit PWA: pin the tab bar to the physical bottom (home-indicator gap).
installNavFlush()

// Offline shell + last-known state. Production only: in dev the SW would serve
// stale bundles and fight Vite's HMR.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* non-fatal */ })
  })
}
