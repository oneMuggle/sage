/* eslint-disable no-undef */  // chrome API + Readability.js + Turndown.js (loaded via script tags)

// Sage Wiki Clipper - Content Script
// 在网页上下文中执行，使用 Readability.js 提取内容，Turndown.js 转换为 Markdown

// 全局类型声明（turndown.js 和 readability.js 通过 manifest 加载）
/**
 * @typedef {Object} ReadabilityArticle
 * @property {string} title
 * @property {string} content
 * @property {string} textContent
 * @property {string} length
 * @property {string} excerpt
 * @property {string} byline
 * @property {string} siteName
 */

/**
 * @typedef {Object} Readability
 * @property {function(document: Document): ReadabilityArticle} parse
 */

/**
 * @typedef {Object} TurndownServiceOptions
 * @property {string} headingStyle
 * @property {string} codeBlockStyle
 * @property {string} emDelimiter
 */

/**
 * @typedef {Object} TurndownService
 * @property {function(string): string} turndown
 * @property {function(string[]): void} remove
 */

(function () {
  'use strict';

  // 监听来自 popup 的消息
  chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
    if (request.action === 'extractContent') {
      try {
        const result = extractContent();
        sendResponse({ success: true, ...result });
      } catch (error) {
        sendResponse({ success: false, error: error.message });
      }
      return true; // 保持消息通道开放
    }
    return false;
  });

  // 提取页面内容
  function extractContent() {
    // 使用 Readability 提取主要内容
    const documentClone = document.cloneNode(true);
    const reader = new Readability(documentClone);
    const article = reader.parse();

    if (!article) {
      throw new Error('无法提取页面内容');
    }

    // 使用 Turndown 将 HTML 转换为 Markdown
    const turndownService = new TurndownService({
      headingStyle: 'atx',
      codeBlockStyle: 'fenced',
      emDelimiter: '_',
    });

    // 移除不需要的元素
    turndownService.remove(['script', 'style', 'noscript', 'iframe', 'nav', 'footer']);

    const markdown = turndownService.turndown(article.content);

    // 构建元数据
    const metadata = {
      title: article.title || document.title,
      url: window.location.href,
      byline: article.byline || '',
      siteName: article.siteName || '',
      excerpt: article.excerpt || '',
      length: article.length || 0,
      markdown: `# ${article.title || document.title}

${article.excerpt ? `> ${article.excerpt}\n\n` : ''}
**来源**: [${article.siteName || window.location.hostname}](${window.location.href})
**作者**: ${article.byline || '未知'}
**剪藏时间**: ${new Date().toISOString()}

---

${markdown}`,
    };

    return metadata;
  }
})();
