// Single source of truth for course color assignment (SPEC-v32-ish plan
// polish). SchoolPage's course rail and Plan's class-meeting blocks must
// agree on which color a course is, or the same class reads as two
// different colors depending on which page you're looking at. The mapping
// is deterministic: a course's tone is purely a function of its alphabetical
// position in state.school.courses, which the backend already returns
// sorted by code, so no id or extra field is needed to keep it stable.

export const COURSE_TONES = ['#8b9cff', '#5eead4', '#fbbf24', '#fb7185', '#c084fc', '#38bdf8']

export function courseTone(courseCode, courses) {
  if (!courseCode || !Array.isArray(courses)) return null
  const index = courses.findIndex((c) => c.code === courseCode)
  if (index < 0) return null
  return COURSE_TONES[index % COURSE_TONES.length]
}
