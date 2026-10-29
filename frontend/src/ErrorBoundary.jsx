// Shows a readable message instead of a blank page when a screen fails to draw,
// with a button to reload (and clear the list filters saved in this browser).
import React from "react";

export default class ErrorBoundary extends React.Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Screen failed to load:", error, info?.componentStack);
  }

  componentDidMount() {
    // moving to another page clears the message
    this.onHash = () => this.state.error && this.setState({ error: null });
    window.addEventListener("hashchange", this.onHash);
  }

  componentWillUnmount() {
    window.removeEventListener("hashchange", this.onHash);
  }

  reset = () => {
    try {
      Object.keys(localStorage)
        .filter((k) => k.startsWith("salestrack.filters."))
        .forEach((k) => localStorage.removeItem(k));
    } catch {
      /* storage not available */
    }
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="crash-screen" role="alert">
        <h1>Something went wrong on this page</h1>
        <p>The page could not be shown. Reloading usually fixes it. If it keeps happening, please tell the team.</p>
        <code>{String(this.state.error?.message || this.state.error)}</code>
        <div className="crash-actions">
          <button className="sf-button" onClick={() => (window.location.hash = "#/home")}>
            Go to Home
          </button>
          <button className="sf-button brand" onClick={this.reset}>
            Reload page
          </button>
        </div>
      </div>
    );
  }
}
