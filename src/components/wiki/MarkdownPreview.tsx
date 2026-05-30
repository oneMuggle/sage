// Markdown Preview - render markdown with code highlighting
import ReactMarkdown from 'react-markdown'

export function MarkdownPreview({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none p-4 text-text-secondary">
      <ReactMarkdown
        components={{
          h1: ({ children }) => <h1 className="text-2xl font-bold text-text mt-6 mb-3">{children}</h1>,
          h2: ({ children }) => <h2 className="text-xl font-semibold text-text mt-5 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="text-lg font-medium text-text mt-4 mb-2">{children}</h3>,
          p: ({ children }) => <p className="mb-3 leading-relaxed">{children}</p>,
          code: ({ className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '')
            const isInline = !match
            return isInline ? (
              <code className="bg-bg-muted px-1.5 py-0.5 rounded text-sm font-mono text-text" {...props}>
                {children}
              </code>
            ) : (
              <div className="bg-bg-muted rounded-lg p-3 my-3 overflow-x-auto">
                <code className={`text-sm font-mono ${className || ''}`} {...props}>
                  {children}
                </code>
              </div>
            )
          },
          ul: ({ children }) => <ul className="list-disc pl-5 mb-3 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 mb-3 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-primary/30 pl-4 py-2 my-3 text-muted italic">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-3">
              <table className="min-w-full border-collapse border border-border text-sm">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border bg-bg-muted px-3 py-2 text-left font-semibold">
              {children}
            </th>
          ),
          td: ({ children }) => <td className="border border-border px-3 py-2">{children}</td>,
          a: ({ href, children }) => (
            <a href={href} className="text-primary hover:underline" target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
