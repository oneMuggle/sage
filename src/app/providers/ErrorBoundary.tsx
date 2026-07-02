import { Component, type ErrorInfo, type ReactNode } from 'react';
import { clientLogger } from '../../shared/log/client';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * 顶层 ErrorBoundary，捕获子树中未处理的渲染错误并展示 fallback UI。
 *
 * - 默认 fallback 展示错误信息 + 重试按钮（重置 state 重渲子树）
 * - 可通过 `fallback` prop 注入自定义 UI
 * - 任何捕获的错误都会 console.error（prod 也能看见）
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    clientLogger.error('react error boundary', {
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined,
      componentStack: info.componentStack,
    });
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  override render() {
    const { error } = this.state;
    if (error) {
      if (this.props.fallback) {
        return this.props.fallback(error, this.reset);
      }
      return (
        <div
          role="alert"
          className="min-h-screen flex flex-col items-center justify-center p-8 bg-bg text-text"
        >
          <h1 className="text-2xl font-semibold mb-2">出错了</h1>
          <p className="text-muted mb-4 text-sm max-w-md text-center">
            {error.message || '未知错误'}
          </p>
          <button
            onClick={this.reset}
            className="px-4 py-2 bg-primary text-text-inverse rounded-radius-sm text-sm hover:bg-primary-hover"
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
