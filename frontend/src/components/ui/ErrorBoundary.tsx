import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErrorState } from "./States";

export class ErrorBoundary extends Component<{ children: ReactNode; label?: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error:", error, info.componentStack);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="p-6">
        <ErrorState title={`${this.props.label ?? "This view"} failed to render`}>
          <p>{this.state.error.message}</p>
          <button className="mt-2 text-mint underline" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </ErrorState>
      </div>
    );
  }
}
