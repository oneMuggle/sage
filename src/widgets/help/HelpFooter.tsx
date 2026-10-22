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

export interface HelpFooterAuditInput {
  externalUrls: string[];
  allLinksHaveNoopener: boolean;
}

export interface HelpFooterAuditReport {
  validHttpsLinkCount: number;
  allLinksHaveNoopener: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateHelpFooterGovernanceAudit(
  input: HelpFooterAuditInput,
): HelpFooterAuditReport {
  const issueCodes: string[] = [];
  const validHttpsLinks = input.externalUrls.filter((url) => url.trim().startsWith('https://'));
  if (input.externalUrls.length === 0) {
    issueCodes.push('HELP_FOOTER_LINKS_EMPTY');
  }
  if (validHttpsLinks.length !== input.externalUrls.length) {
    issueCodes.push('HELP_FOOTER_INSECURE_EXTERNAL_URL');
  }
  if (!input.allLinksHaveNoopener) {
    issueCodes.push('HELP_FOOTER_NOOPENER_MISSING');
  }
  return {
    validHttpsLinkCount: validHttpsLinks.length,
    allLinksHaveNoopener: input.allLinksHaveNoopener,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
