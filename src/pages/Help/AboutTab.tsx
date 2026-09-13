import contributors from '../../content/about/contributors.json';
import { VISION, PHILOSOPHY } from '../../content/about/vision';
import { BrandLogo } from '../../shared/ui';

export function AboutTab() {
  return (
    <div className="max-w-3xl mx-auto px-8 py-8">
      {/* Brand Header */}
      <div className="text-center mb-12">
        <BrandLogo size="lg" />
        <h1 className="text-3xl font-bold mt-6 text-text">Sage v{__APP_VERSION__}</h1>
        <p className="text-lg text-text-secondary mt-2">记忆型 AI 桌面助手</p>
      </div>

      {/* Vision Section */}
      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-4 text-text flex items-center gap-2">
          <span>🎯</span>
          <span>应用愿景</span>
        </h2>
        <div className="prose prose-invert max-w-none">
          <p className="text-text leading-relaxed whitespace-pre-line">{VISION}</p>
        </div>
      </section>

      {/* Philosophy Section */}
      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-4 text-text flex items-center gap-2">
          <span>💡</span>
          <span>设计理念</span>
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {PHILOSOPHY.map((item) => (
            <div
              key={item.principle}
              className="p-4 rounded-radius-sm border border-border bg-surface hover:bg-bg-hover transition-colors"
            >
              <h3 className="text-lg font-semibold mb-2 text-text">{item.principle}</h3>
              <p className="text-sm text-text-secondary">{item.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Contributors Section */}
      <section className="mb-10">
        <h2 className="text-2xl font-semibold mb-4 text-text flex items-center gap-2">
          <span>👥</span>
          <span>贡献者</span>
        </h2>
        <div className="space-y-4">
          {contributors.core.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-text-secondary mb-2">核心开发</h3>
              <p className="text-text">{contributors.core.join(', ')}</p>
            </div>
          )}
          {contributors.contributors.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-text-secondary mb-2">贡献者</h3>
              <p className="text-text">{contributors.contributors.join(', ')}</p>
            </div>
          )}
          {contributors.specialThanks.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-text-secondary mb-2">特别感谢</h3>
              <p className="text-text">{contributors.specialThanks.join(', ')}</p>
            </div>
          )}
        </div>
      </section>

      {/* System Information */}
      <section>
        <h2 className="text-2xl font-semibold mb-4 text-text flex items-center gap-2">
          <span>ℹ️</span>
          <span>系统信息</span>
        </h2>
        <dl className="grid grid-cols-2 gap-4">
          <SystemInfoItem label="版本" value={__APP_VERSION__} />
          <SystemInfoItem label="Electron" value={process.versions.electron} />
          <SystemInfoItem label="Node.js" value={process.versions.node} />
          <SystemInfoItem label="Python" value="3.10+" />
          <SystemInfoItem label="许可证" value="MIT" />
          <SystemInfoItem label="架构" value={process.arch} />
          <SystemInfoItem label="平台" value={process.platform} />
        </dl>
      </section>
    </div>
  );
}

function SystemInfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-sm font-medium text-text-secondary">{label}:</dt>
      <dd className="text-sm text-text">{value}</dd>
    </div>
  );
}
