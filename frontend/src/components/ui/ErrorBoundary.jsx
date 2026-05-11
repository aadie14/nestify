import React from 'react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: String(error?.message || 'Unexpected UI error'),
    };
  }

  componentDidCatch(error, errorInfo) {
    // Keep logs available in devtools while providing a safe fallback UI.
    // eslint-disable-next-line no-console
    console.error('UI crash captured by ErrorBoundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="neo-page" style={{ minHeight: '70vh', alignItems: 'center' }}>
          <section className="neo-panel glass" style={{ maxWidth: 760, margin: '64px auto', width: '100%' }}>
            <div className="neo-kicker">Recovered From Crash</div>
            <h2 style={{ marginTop: 0 }}>UI encountered an unexpected error</h2>
            <p style={{ color: '#9bb1cc' }}>
              The app is still running. Refresh this page to continue.
            </p>
            <div className="neo-attempt-item" style={{ marginTop: 10 }}>
              <div className="neo-attempt-title">Error</div>
              <div className="neo-attempt-meta">{this.state.message}</div>
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
              <button className="neo-tab active" type="button" onClick={() => window.location.reload()}>
                Reload UI
              </button>
            </div>
          </section>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
