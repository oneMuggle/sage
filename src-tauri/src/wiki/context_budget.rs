// Wiki token 预算分配
//
// 设计要点:
// - 极简 token 计数:text.len() / 3 (UTF-8 平均),不引 tiktoken-rs
// - 50% 给检索结果 / 30% 历史+系统 / 5% index / 15% 留 LLM 输出
// - 单页硬上限 = total / 8(防止一坨内容压垮)

/// 默认预算分配比例
pub const PAGES_RATIO: f64 = 0.50;
pub const HISTORY_RATIO: f64 = 0.30;
pub const INDEX_RATIO: f64 = 0.05;
pub const RESERVE_RATIO: f64 = 0.15;
pub const PER_PAGE_DIVISOR: u32 = 8;
/// 简易 token 估算:UTF-8 字符数 / 3
pub const CHARS_PER_TOKEN: u32 = 3;
/// 默认总 token 上限(8K,大多数模型够用)
pub const DEFAULT_MAX_TOKENS: u32 = 8192;

#[derive(Debug, Clone, PartialEq)]
pub struct ContextBudget {
    pub total: u32,
    pub pages: u32,
    pub history: u32,
    pub index: u32,
    pub response_reserve: u32,
    pub per_page_cap: u32,
}

impl ContextBudget {
    /// 根据模型 max_tokens 计算预算
    pub fn compute(model_max_tokens: u32) -> Self {
        let total = model_max_tokens.min(DEFAULT_MAX_TOKENS) * 7 / 10; // 70% 上限
        let pages = (total as f64 * PAGES_RATIO) as u32;
        let history = (total as f64 * HISTORY_RATIO) as u32;
        let index = (total as f64 * INDEX_RATIO) as u32;
        let response_reserve = (total as f64 * RESERVE_RATIO) as u32;
        let per_page_cap = total / PER_PAGE_DIVISOR;
        Self {
            total,
            pages,
            history,
            index,
            response_reserve,
            per_page_cap,
        }
    }

    /// 估算 token 数(text.chars().count() / CHARS_PER_TOKEN 向上取整)
    pub fn estimate_tokens(text: &str) -> u32 {
        (text.chars().count() as u32).div_ceil(CHARS_PER_TOKEN)
    }
}

/// 截断的页面片段
#[derive(Debug, Clone, PartialEq)]
pub struct PageChunk {
    pub page_path: String,
    pub content: String,
    pub truncated: bool,
}

/// 把 pages 截断到预算范围内
///
/// 策略:
/// 1. 先按 budget.pages 算可用 token 数
/// 2. 按输入顺序累加,每个 page 实际内容不超过 per_page_cap
/// 3. 累计到上限后停止
pub fn truncate_pages(
    pages: &[(String, String)],
    budget: &ContextBudget,
) -> Vec<PageChunk> {
    let mut out = Vec::new();
    let mut remaining = budget.pages;
    for (path, content) in pages {
        if remaining == 0 {
            break;
        }
        let full_tokens = ContextBudget::estimate_tokens(content);
        // 实际允许此 page 用的 token 数 = min(full_tokens, per_page_cap, remaining)
        let allowed_tokens = full_tokens.min(budget.per_page_cap).min(remaining);
        let max_chars = (allowed_tokens * CHARS_PER_TOKEN) as usize;
        let truncated = full_tokens > allowed_tokens;
        let actual_content: String = content.chars().take(max_chars).collect();
        out.push(PageChunk {
            page_path: path.clone(),
            content: actual_content,
            truncated,
        });
        remaining = remaining.saturating_sub(allowed_tokens);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn budget_compute_total_is_70pct() {
        let b = ContextBudget::compute(8192);
        assert_eq!(b.total, 8192 * 7 / 10); // 70%
    }

    #[test]
    fn budget_caps_at_default_max() {
        let b = ContextBudget::compute(100_000);
        assert!(b.total <= DEFAULT_MAX_TOKENS * 7 / 10);
    }

    #[test]
    fn budget_ratios_sum_to_100pct() {
        let b = ContextBudget::compute(8192);
        let sum = b.pages + b.history + b.index + b.response_reserve;
        // 允许 ±1 误差(整数除法)
        assert!((sum as i32 - b.total as i32).abs() <= 1);
    }

    #[test]
    fn per_page_cap_is_total_over_8() {
        let b = ContextBudget::compute(8192);
        assert_eq!(b.per_page_cap, b.total / 8);
    }

    #[test]
    fn estimate_tokens_basic() {
        assert_eq!(ContextBudget::estimate_tokens(""), 0);
        assert_eq!(ContextBudget::estimate_tokens("abc"), 1);
        assert_eq!(ContextBudget::estimate_tokens("hello world"), 4); // 11 字符 / 3 = 4(向上取整)
    }

    #[test]
    fn truncate_pages_within_budget() {
        let b = ContextBudget::compute(1024); // total = 716, pages = 358
        let pages = vec![
            ("a".to_string(), "short content".to_string()),
            ("b".to_string(), "another short".to_string()),
        ];
        let chunks = truncate_pages(&pages, &b);
        assert_eq!(chunks.len(), 2);
        assert!(!chunks[0].truncated);
        assert!(!chunks[1].truncated);
    }

    #[test]
    fn truncate_pages_huge_content_truncated() {
        let b = ContextBudget::compute(1024); // total=716, pages=358, per_page_cap=89
        let huge = "x".repeat(2000); // > 89 tokens (> 267 chars)
        let pages = vec![("a".to_string(), huge)];
        let chunks = truncate_pages(&pages, &b);
        assert_eq!(chunks.len(), 1);
        assert!(chunks[0].truncated);
        // 截断后不超过 per_page_cap * CHARS_PER_TOKEN = 89 * 3 = 267 字符
        assert!(chunks[0].content.chars().count() <= 89 * CHARS_PER_TOKEN as usize);
    }

    #[test]
    fn truncate_pages_stops_when_budget_exhausted() {
        // total=179, pages=89, per_page_cap=22
        // 5 个 huge page → 依次装入,每个 min(667, 22, remaining) 直到 remaining=0
        // 第 5 个装入 1 token,第 6 个被跳过
        let b = ContextBudget::compute(256);
        let pages = vec![
            ("a".to_string(), "x".repeat(2000)),
            ("b".to_string(), "y".repeat(2000)),
            ("c".to_string(), "z".repeat(2000)),
            ("d".to_string(), "w".repeat(2000)),
            ("e".to_string(), "v".repeat(2000)),
            ("f".to_string(), "u".repeat(2000)),
        ];
        let chunks = truncate_pages(&pages, &b);
        // 22+22+22+22+1 = 89 → 5 个装入,第 6 个被跳过
        assert_eq!(chunks.len(), 5);
        assert_eq!(chunks[0].page_path, "a");
        assert_eq!(chunks[4].page_path, "e");
    }
}
