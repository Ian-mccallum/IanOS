import { useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import GrowthMark from '../components/GrowthMark.jsx'

function SuggestedTopicCard({ proposal, onStart }) {
  return (
    <div className="learning-suggested-card glass-card glass-card-pad">
      <span className="section-label">Suggested by Mr. Miyagi</span>
      <p className="learning-suggested-text">{proposal.action}</p>
      <button className="btn ghost" onClick={() => onStart(proposal.action)}>
        Start this topic
      </button>
    </div>
  )
}

function TopicCard({ topic, onOpen }) {
  return (
    <button className="learning-topic-card glass-card glass-card-pad" onClick={onOpen}>
      <GrowthMark count={topic.confirmed_count} />
      <span className="learning-topic-name">{topic.name}</span>
    </button>
  )
}

export default function LearningPage({ state, refresh, toast, requestConsult }) {
  const [name, setName] = useState('')
  const [pendingOrigin, setPendingOrigin] = useState('user')
  const [busy, setBusy] = useState(false)
  const reduced = useReducedMotion()
  const learningState = state.learning || { topics: [], today: null, streak: { streak: 0, stools: 2 } }
  const suggested = (state.pending_proposals || []).filter(
    (p) => p.role === 'tutor' && p.status === 'PENDING' && p.kind === 'task'
  )

  function startFromSuggestion(actionText) {
    setName(actionText)
    setPendingOrigin('agent_proposed')
  }

  async function addTopic(e) {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    try {
      const out = await api('/api/learning/topics', 'POST', { name: trimmed, origin: pendingOrigin })
      setName('')
      setPendingOrigin('user')
      refresh?.()
      requestConsult?.(out.consultRequest)
    } catch (err) {
      toast?.(err.message || 'could not add topic', 'crit')
    } finally {
      setBusy(false)
    }
  }

  function openToday() {
    const today = learningState.today
    requestConsult?.({
      role: 'tutor',
      seedText: today?.thread_id ? '' : (today?.task_prompt || ''),
    })
  }

  const todayOpen = learningState.today && learningState.today.status !== 'completed'

  return (
    <div className="learning-page page-stack">
      {todayOpen && (
        <motion.button
          type="button"
          className="today-row today-row--practice"
          onClick={openToday}
          initial={reduced ? false : { opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
        >
          <span className="today-row-check today-row-check--practice">Practice</span>
          <span className="today-row-title">
            {learningState.today.task_prompt || "Continue today's session"}
          </span>
        </motion.button>
      )}

      {learningState.topics.length > 0 && (
        <div className="learning-topics">
          {learningState.topics.map((t) => (
            <TopicCard
              key={t.id}
              topic={t}
              onOpen={() => requestConsult?.({ role: 'tutor', seedText: '' })}
            />
          ))}
        </div>
      )}

      {suggested.map((p) => (
        <SuggestedTopicCard key={p.id} proposal={p} onStart={startFromSuggestion} />
      ))}

      <form className="learning-add glass-card glass-card-pad" onSubmit={addTopic}>
        <textarea
          className="gf-field gf-grow learning-add-field"
          rows={1}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              addTopic(e)
            }
          }}
          placeholder="Add a topic"
          disabled={busy}
        />
      </form>
    </div>
  )
}
