export function HelpFooter() {
  return (
    <div className="border-t border-border bg-surface px-6 py-3">
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-4">
          <a
            href="https://github.com/oneMuggle/sage/tree/main/docs/user-manual"
            target="_blank"
            rel="noopener noreferrer"
            className="text-text-secondary hover:text-primary transition-colors flex items-center gap-1"
          >
            <span>📖</span>
            <span>完整文档</span>
          </a>
          <a
            href="https://github.com/oneMuggle/sage/issues/new"
            target="_blank"
            rel="noopener noreferrer"
            className="text-text-secondary hover:text-primary transition-colors flex items-center gap-1"
          >
            <span>💬</span>
            <span>反馈问题</span>
          </a>
        </div>
        <a
          href="https://github.com/oneMuggle/sage"
          target="_blank"
          rel="noopener noreferrer"
          className="text-text-secondary hover:text-primary transition-colors flex items-center gap-1"
        >
          <span>🔗</span>
          <span>GitHub</span>
        </a>
      </div>
    </div>
  );
}
