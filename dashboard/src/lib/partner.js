function active(rows) {
  return (rows || []).filter((row) => row && !row.deleted_at)
}

function compareIds(a, b) {
  const aNumber = typeof a === 'number' ? a : Number.NaN
  const bNumber = typeof b === 'number' ? b : Number.NaN
  if (Number.isFinite(aNumber) && Number.isFinite(bNumber)) return aNumber - bNumber
  return String(a).localeCompare(String(b))
}

export function groupComplete(parent, children = []) {
  return Boolean(parent?.done) && children.every((child) => Boolean(child.done))
}

export function groupTasks(rows) {
  const visible = active(rows)
  const parents = visible
    .filter((row) => row.parent_id == null)
    .sort((a, b) => compareIds(a.id, b.id))
  const children = new Map()

  for (const row of visible) {
    if (row.parent_id == null) continue
    const siblings = children.get(row.parent_id) || []
    siblings.push(row)
    children.set(row.parent_id, siblings)
  }

  return parents.map((parent) => {
    const childRows = (children.get(parent.id) || []).sort((a, b) => compareIds(a.id, b.id))
    return {
      parent,
      children: childRows,
      complete: groupComplete(parent, childRows),
    }
  })
}

export function actionableTasks(rows) {
  return groupTasks(rows).flatMap(({ parent, children }) => {
    const unfinishedChildren = children.filter((child) => !child.done)
    if (unfinishedChildren.length) return unfinishedChildren
    return parent.done ? [] : [parent]
  })
}

export function openCount(rows) {
  return actionableTasks(rows).length
}

export function nextAction(rows) {
  return actionableTasks(rows)[0] || null
}
