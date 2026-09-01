import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  actionableTasks,
  groupTasks,
  nextAction,
  openCount,
} from '../src/lib/partner.js'

const fixtureUrl = new URL('../../tests/fixtures/partner_semantics.json', import.meta.url)
const cases = JSON.parse(await readFile(fixtureUrl, 'utf8'))

for (const fixture of cases) {
  test(`Partner semantics: ${fixture.name}`, () => {
    const groups = groupTasks(fixture.rows).map(({ parent, children, complete }) => ({
      parent_id: parent.id,
      child_ids: children.map((child) => child.id),
      complete,
    }))

    assert.deepEqual(groups, fixture.expected.groups)
    assert.deepEqual(actionableTasks(fixture.rows).map((task) => task.id), fixture.expected.actionable_ids)
    assert.equal(openCount(fixture.rows), fixture.expected.open_count)
    assert.equal(nextAction(fixture.rows)?.id ?? null, fixture.expected.next_action_id)
  })
}

