import React from 'react'

/**
 * A private School note must never take down the rest of the dashboard. The
 * workspace owns a rich editor and several optional shelves, so this boundary
 * turns an unexpected rendering fault into a clear recovery path instead of a
 * black route.
 */
export default class SchoolNotebookBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error) {
    // Keep the useful diagnostic in the local developer console without
    // sending note data or stack traces anywhere.
    console.error('School notebook could not render', error)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <section className="school-notebook-recovery panel" role="alert">
        <div className="panel-body">
          <p className="school-notebook-recovery-label">Class notes</p>
          <h2>That note did not open.</h2>
          <p>Nothing was deleted. Try the notebook again, or return to School and open the session from your schedule.</p>
          <div className="school-notebook-recovery-actions">
            <button type="button" className="btn primary" onClick={() => this.setState({ error: null })}>Try again</button>
            <button type="button" className="btn" onClick={this.props.onBack}>Back to School</button>
          </div>
        </div>
      </section>
    )
  }
}
