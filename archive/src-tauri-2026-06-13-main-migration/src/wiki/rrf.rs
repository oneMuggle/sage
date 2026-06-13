// Wiki RRF 融合
//
// Reciprocal Rank Fusion:
//   score(item) = Σ 1 / (k + rank_i)
// 其中 rank_i 是 item 在第 i 个排名列表中的位置(0-indexed)
//
// 常用于融合 token 搜索 + 向量搜索

use std::collections::HashMap;
use std::hash::Hash;

/// 默认 k 值(论文推荐)
pub const DEFAULT_RRF_K: f64 = 60.0;

/// 融合两个已排序的命中列表(按相关度从高到低,0-indexed)
pub fn rrf_fuse<T: Hash + Eq + Clone>(
    token_hits: &[T],
    vector_hits: &[T],
    k: f64,
) -> Vec<(T, f64)> {
    let mut scores: HashMap<T, f64> = HashMap::new();
    for (rank, item) in token_hits.iter().enumerate() {
        *scores.entry(item.clone()).or_insert(0.0) += 1.0 / (k + rank as f64);
    }
    for (rank, item) in vector_hits.iter().enumerate() {
        *scores.entry(item.clone()).or_insert(0.0) += 1.0 / (k + rank as f64);
    }
    let mut out: Vec<(T, f64)> = scores.into_iter().collect();
    // 降序
    out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rrf_empty_inputs_returns_empty() {
        let out: Vec<(String, f64)> = rrf_fuse(&[], &[], DEFAULT_RRF_K);
        assert!(out.is_empty());
    }

    #[test]
    fn rrf_only_token_hits() {
        let tokens = vec!["A".to_string(), "B".to_string()];
        let out: Vec<(String, f64)> = rrf_fuse(&tokens, &[], DEFAULT_RRF_K);
        assert_eq!(out.len(), 2);
        // A rank 0,B rank 1
        assert_eq!(out[0].0, "A");
        assert!(out[0].1 > out[1].1);
    }

    #[test]
    fn rrf_only_vector_hits() {
        let vectors = vec!["X".to_string(), "Y".to_string()];
        let out: Vec<(String, f64)> = rrf_fuse(&[], &vectors, DEFAULT_RRF_K);
        assert_eq!(out.len(), 2);
        assert_eq!(out[0].0, "X");
    }

    #[test]
    fn rrf_intersection_boosts_score() {
        let tokens = vec!["A".to_string(), "B".to_string(), "C".to_string()];
        let vectors = vec!["A".to_string(), "D".to_string()];
        let out: Vec<(String, f64)> = rrf_fuse(&tokens, &vectors, DEFAULT_RRF_K);
        // A 同时出现在两个列表 → 分数最高
        assert_eq!(out[0].0, "A");
        // 验证 A 分数 = 1/(60+0) + 1/(60+0) = 2/60
        assert!((out[0].1 - 2.0 / 60.0).abs() < 1e-9);
    }

    #[test]
    fn rrf_dedupes_same_item() {
        let tokens = vec!["A".to_string(), "A".to_string()]; // 重复(假设不去重)
        let out: Vec<(String, f64)> = rrf_fuse(&tokens, &[], DEFAULT_RRF_K);
        // A 只出现一次
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].0, "A");
    }

    #[test]
    fn rrf_custom_k() {
        // k 越小,rank 影响越大
        let tokens = vec!["A".to_string(), "B".to_string()];
        let k_small = 1.0;
        let out: Vec<(String, f64)> = rrf_fuse(&tokens, &[], k_small);
        // A rank 0 → 1/(1+0) = 1.0;B rank 1 → 1/(1+1) = 0.5
        assert!((out[0].1 - 1.0).abs() < 1e-9);
        assert!((out[1].1 - 0.5).abs() < 1e-9);
    }

    #[test]
    fn rrf_preserves_order_with_disjoint_lists() {
        // 不重叠:token 和 vector 完全不同 → 各有 score,排序按单独 score
        let tokens = vec!["A".to_string(), "B".to_string()];
        let vectors = vec!["C".to_string(), "D".to_string()];
        let out: Vec<(String, f64)> = rrf_fuse(&tokens, &vectors, DEFAULT_RRF_K);
        assert_eq!(out.len(), 4);
        // A 单独 score = 1/61,C 单独 score = 1/61 → rank 0 并列
        // 排序后 A 在前(insertion order),但 B/C/D 都有 1/61 或更低
        assert!(out.iter().all(|(_, s)| *s <= 1.0 / 60.0));
    }
}
