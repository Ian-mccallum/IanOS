/**
 * Special-character sets for class notes, by course (Ian, 2026-09-10).
 *
 * Only Viking Mythology has one. A course with no entry gets no picker, no
 * toolbar button and no shortcut at all, so the key combo stays free in every
 * other notebook.
 *
 * Normalized Old Norse, the convention Ian's course uses, with the modern
 * Icelandic o-umlaut for the o-ogonek sound (Völsung) and the o-ogonek itself
 * for editions that keep it. His first notes in the course had none of
 * these letters, only the nearest-looking ASCII typed in their place (a p or
 * a b for þ, an o for ð, AE for Æ).
 *
 * No React here, so node --test can cover it directly.
 */

export const CHARACTER_SETS = {
  old_norse: {
    label: 'Old Norse',
    lower: ['á', 'é', 'í', 'ó', 'ú', 'ý', 'þ', 'ð', 'æ', 'ö', 'ǫ', 'ø', 'œ'],
    upper: ['Á', 'É', 'Í', 'Ó', 'Ú', 'Ý', 'Þ', 'Ð', 'Æ', 'Ö', 'Ǫ', 'Ø', 'Œ'],
  },
}

export const COURSE_CHARACTER_SETS = {
  'SPAN 210': 'old_norse',
}

export function characterSetFor(courseCode) {
  const key = COURSE_CHARACTER_SETS[courseCode]
  return key ? CHARACTER_SETS[key] : null
}

/**
 * The plain letter each character is typed from, so the picker can be driven
 * without the mouse: t is þ (the "th" sound), d is ð, and a letter with
 * several variants cycles through them (o: ó ö ǫ ø œ, a: á æ).
 */
export const BASE_LETTER = {
  á: 'a', é: 'e', í: 'i', ó: 'o', ú: 'u', ý: 'y',
  þ: 't', ð: 'd', æ: 'a', ö: 'o', ǫ: 'o', ø: 'o', œ: 'o',
}

/**
 * The next position in `row` whose base letter is `key`, searching forward
 * from `from` and wrapping, or -1. Starting from the current position (not
 * the start of the row) is what makes a second press of the same letter
 * move on to that letter's next variant.
 */
export function nextIndexForKey(row, key, from = -1) {
  if (typeof key !== 'string' || key.length !== 1) return -1
  const target = key.toLowerCase()
  const size = row.length
  for (let step = 1; step <= size; step += 1) {
    const index = (((from + step) % size) + size) % size
    if (BASE_LETTER[row[index].toLowerCase()] === target) return index
  }
  return -1
}

/**
 * Where a keypress in the picker should land. A fresh letter goes to its
 * first variant; pressing the letter the focus is already on moves on to the
 * next one. Continuing from the current position on every press sent "o"
 * typed while sitting on þ to ö instead of ó in live testing.
 */
export function jumpIndex(row, key, current = -1) {
  const onSameLetter = current >= 0 && current < row.length
    && BASE_LETTER[row[current].toLowerCase()] === (typeof key === 'string' ? key.toLowerCase() : '')
  return nextIndexForKey(row, key, onSameLetter ? current : -1)
}
