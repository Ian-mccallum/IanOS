import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const dashboardUrl = new URL('../', import.meta.url)
const source = (path) => readFileSync(new URL(path, dashboardUrl), 'utf8')

test('overview roots expose page roles without turning sparse panels into workspaces', () => {
  assert.match(source('src/pages/CommandPage.jsx'), /command-page page-layout page-layout--overview/)
  assert.match(source('src/pages/BodyPage.jsx'), /body-page page-layout page-layout--overview/)
  assert.match(source('src/pages/PartnerPage.jsx'), /partner-page page-layout page-layout--overview/)
  assert.match(source('src/pages/MemoryPage.jsx'), /memory-page page-layout page-layout--overview/)
})

test('overview pages group genuine parallel work before desktop grids', () => {
  const command = source('src/pages/CommandPage.jsx')
  const body = source('src/pages/BodyPage.jsx')
  const partner = source('src/pages/PartnerPage.jsx')
  const memory = source('src/pages/MemoryPage.jsx')
  const css = source('src/styles.css')

  assert.match(command, /command-page page-layout page-layout--overview/)
  assert.match(body, /className="body-training-column"/)
  assert.match(partner, /className="partner-sidebar"/)
  assert.match(partner, /className="partner-workstream"/)
  assert.match(memory, /className="memory-tools"/)
  assert.match(memory, /className="memory-records"/)

  assert.match(css, /\.body-page \{[\s\S]*?display: grid;[\s\S]*?grid-template-columns: minmax\(480px, 1\.15fr\) minmax\(340px, 0\.85fr\)/)
  assert.match(css, /\.partner-page \{[\s\S]*?display: grid;[\s\S]*?grid-template-columns: minmax\(300px, 380px\) minmax\(0, 1fr\)/)
  assert.match(css, /\.memory-page \{[\s\S]*?display: grid;[\s\S]*?grid-template-columns: minmax\(300px, 380px\) minmax\(0, 1fr\)/)
  assert.match(css, /@media \(min-width: 1100px\) \{[\s\S]*?\.command-grid \{[\s\S]*?grid-template-columns: minmax\(0, 480px\) minmax\(280px, 340px\)/)
})

test('School workspace uses the remaining viewport height without stretching its intermediate row', () => {
  const css = source('src/styles.css')

  assert.match(css, /\.school-page\.page-layout--workspace > \.school-command \{ flex: 1 1 0; min-height: 0; \}/)
  assert.match(css, /grid-template-rows: minmax\(300px, 0\.9fr\) minmax\(0, 1fr\)/)
})
