import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

/**
 * Theme 子树的局部错误边界：捕获主题系统内部渲染错误，
 * 防止崩溃扩散到整个应用（顶层 ErrorBoundary 仍可兜底）。
 *
 * - 默认 fallback 显示一段友好的提示 + 错误信息
 * - 可通过 `fallback` prop 注入自定义 UI（一般用于 inline 场景）
 */
export class ThemeErrorBoundary extends Component<Props, State> {
  override state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('[ThemeErrorBoundary] caught:', error, info);
  }

  override render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div role="alert" data-testid="theme-fallback">
          <p>主题系统异常,已使用默认。</p>
          {this.state.error && <pre>{this.state.error.message}</pre>}
        </div>
      );
    }
    return this.props.children;
  }
}