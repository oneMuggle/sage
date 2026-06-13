// Wiki VectorStore - 纯 Rust 嵌入式向量存储
//
// 设计要点:
// - 零新依赖:仅用 std + serde + serde_json
// - 文件存储: {project_root}/.llm-wiki/vectors.json
// - 内存索引:启动时全量加载,upsert/delete 后 flush
// - 检索:brute-force cosine similarity + top-k
// - 规模上限:适合 < 1万 chunk;超过需要切换到 HNSW 索引

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

// ============================================================================
// 类型
// ============================================================================

/// 单个 chunk 的向量记录
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ChunkRecord {
    /// 唯一 ID: `{page_path}::{chunk_index}`
    pub id: String,
    /// wiki 页面相对路径,如 `wiki/sources/albert-einstein.md`
    pub page_path: String,
    /// 在该页内的 chunk 序号
    pub chunk_index: u32,
    /// chunk 文本内容(便于回显)
    pub content: String,
    /// 向量(默认 1536 维,text-embedding-3-small)
    pub vector: Vec<f32>,
}

/// JSON 文件整体结构(便于版本演进)
#[derive(Debug, Clone, Serialize, Deserialize)]
struct StorageFile {
    version: u32,
    dim: u32,
    records: Vec<ChunkRecord>,
}

/// 搜索结果
#[derive(Debug, Clone, PartialEq)]
pub struct SearchHit {
    pub page_path: String,
    pub chunk_index: u32,
    pub content: String,
    pub score: f32,
}

// ============================================================================
// VectorStore
// ============================================================================

/// 嵌入式向量存储(纯 Rust,JSON 后端)
pub struct VectorStore {
    storage_path: PathBuf,
    dim: u32,
    records: Vec<ChunkRecord>,
    /// page_path -> 该页的 chunk 索引集合(快速 delete)
    by_page: HashMap<String, Vec<u32>>,
}

impl VectorStore {
    /// 打开或创建项目级 vector store
    pub fn open(project_root: &Path, dim: u32) -> Result<Self, String> {
        let storage_path = project_root.join(".llm-wiki/vectors.json");
        let records = if storage_path.exists() {
            let body = fs::read_to_string(&storage_path)
                .map_err(|e| format!("读取向量库失败: {}", e))?;
            let parsed: StorageFile = serde_json::from_str(&body)
                .map_err(|e| format!("解析向量库失败: {}", e))?;
            if parsed.dim != dim {
                return Err(format!(
                    "向量维度不匹配: 文件={}, 期望={}",
                    parsed.dim, dim
                ));
            }
            parsed.records
        } else {
            Vec::new()
        };
        let mut by_page: HashMap<String, Vec<u32>> = HashMap::new();
        for r in &records {
            by_page.entry(r.page_path.clone()).or_default().push(r.chunk_index);
        }
        Ok(Self {
            storage_path,
            dim,
            records,
            by_page,
        })
    }

    /// upsert 一个页面的所有 chunk(同 page_path 先删后增)
    pub fn upsert_chunks(
        &mut self,
        page_path: &str,
        chunks: &[(u32, String, Vec<f32>)],
    ) -> Result<(), String> {
        // 校验维度
        for (_, _, v) in chunks {
            if v.len() as u32 != self.dim {
                return Err(format!(
                    "chunk 向量维度 {} 与 store 维度 {} 不匹配",
                    v.len(),
                    self.dim
                ));
            }
        }
        // 先删除该页旧记录
        self.delete_by_page(page_path);
        // 追加新记录
        for (idx, content, vector) in chunks {
            let id = format!("{}::{}", page_path, idx);
            self.records.push(ChunkRecord {
                id,
                page_path: page_path.to_string(),
                chunk_index: *idx,
                content: content.clone(),
                vector: vector.clone(),
            });
            self.by_page
                .entry(page_path.to_string())
                .or_default()
                .push(*idx);
        }
        self.flush()
    }

    /// 删除一个页面的所有 chunk
    pub fn delete_by_page(&mut self, page_path: &str) -> usize {
        let before = self.records.len();
        self.records.retain(|r| r.page_path != page_path);
        let removed = before - self.records.len();
        self.by_page.remove(page_path);
        removed
    }

    /// 全文 brute-force cosine 搜索,返回 top-k
    pub fn search(&self, query_vec: &[f32], limit: usize) -> Result<Vec<SearchHit>, String> {
        if query_vec.len() as u32 != self.dim {
            return Err(format!(
                "query 向量维度 {} 与 store 维度 {} 不匹配",
                query_vec.len(),
                self.dim
            ));
        }
        let q_norm = vector_norm(query_vec);
        if q_norm == 0.0 {
            return Ok(Vec::new());
        }
        let mut scored: Vec<SearchHit> = self
            .records
            .iter()
            .map(|r| {
                let r_norm = vector_norm(&r.vector);
                let score = if r_norm == 0.0 {
                    0.0
                } else {
                    dot_product(query_vec, &r.vector) / (q_norm * r_norm)
                };
                SearchHit {
                    page_path: r.page_path.clone(),
                    chunk_index: r.chunk_index,
                    content: r.content.clone(),
                    score,
                }
            })
            .collect();
        // 降序
        scored.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(limit);
        Ok(scored)
    }

    /// 当前存储的 chunk 数量
    pub fn len(&self) -> usize {
        self.records.len()
    }

    /// 是否为空
    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }

    /// 把内存状态写回磁盘
    fn flush(&self) -> Result<(), String> {
        if let Some(parent) = self.storage_path.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("创建 .llm-wiki 目录失败: {}", e))?;
        }
        let file = StorageFile {
            version: 1,
            dim: self.dim,
            records: self.records.clone(),
        };
        let json = serde_json::to_string_pretty(&file)
            .map_err(|e| format!("序列化向量库失败: {}", e))?;
        // 原子写
        let tmp = self.storage_path.with_extension("json.tmp");
        fs::write(&tmp, json).map_err(|e| format!("写临时向量库失败: {}", e))?;
        fs::rename(&tmp, &self.storage_path).map_err(|e| format!("rename 向量库失败: {}", e))?;
        Ok(())
    }
}

// ============================================================================
// 工具函数
// ============================================================================

fn dot_product(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b.iter()).map(|(x, y)| x * y).sum()
}

fn vector_norm(v: &[f32]) -> f32 {
    v.iter().map(|x| x * x).sum::<f32>().sqrt()
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    fn tmp_project(name: &str) -> PathBuf {
        let dir = env::temp_dir().join(format!("sage-wiki-vs-test-{}-{}", name, std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn vec3(a: f32, b: f32, c: f32) -> Vec<f32> {
        vec![a, b, c]
    }

    // ---- open / 持久化 ----

    #[test]
    fn open_empty_when_file_missing() {
        let dir = tmp_project("open-empty");
        let store = VectorStore::open(&dir, 3).unwrap();
        assert_eq!(store.len(), 0);
        assert!(store.is_empty());
    }

    #[test]
    fn open_persists_and_reloads() {
        let dir = tmp_project("persist");
        {
            let mut store = VectorStore::open(&dir, 3).unwrap();
            store
                .upsert_chunks(
                    "wiki/sources/a.md",
                    &[(0, "hello".to_string(), vec3(1.0, 0.0, 0.0))],
                )
                .unwrap();
            assert_eq!(store.len(), 1);
        }
        // 重新打开
        let store2 = VectorStore::open(&dir, 3).unwrap();
        assert_eq!(store2.len(), 1);
        let r = &store2.records[0];
        assert_eq!(r.page_path, "wiki/sources/a.md");
        assert_eq!(r.chunk_index, 0);
        assert_eq!(r.vector, vec3(1.0, 0.0, 0.0));
    }

    #[test]
    fn open_with_mismatched_dim_errors() {
        let dir = tmp_project("dim-mismatch");
        {
            let mut store = VectorStore::open(&dir, 3).unwrap();
            store
                .upsert_chunks("p", &[(0, "x".to_string(), vec3(1.0, 0.0, 0.0))])
                .unwrap();
        }
        // 用不同 dim 打开应失败
        let res = VectorStore::open(&dir, 4);
        assert!(res.is_err());
    }

    // ---- upsert ----

    #[test]
    fn upsert_replaces_existing_page_chunks() {
        let dir = tmp_project("upsert-replace");
        let mut store = VectorStore::open(&dir, 3).unwrap();
        // 第一次:2 个 chunk
        store
            .upsert_chunks(
                "p",
                &[
                    (0, "v0".to_string(), vec3(1.0, 0.0, 0.0)),
                    (1, "v1".to_string(), vec3(0.0, 1.0, 0.0)),
                ],
            )
            .unwrap();
        assert_eq!(store.len(), 2);
        // 第二次:同 page 1 个 chunk → 应替换
        store
            .upsert_chunks("p", &[(0, "new".to_string(), vec3(0.0, 0.0, 1.0))])
            .unwrap();
        assert_eq!(store.len(), 1);
        assert_eq!(store.records[0].content, "new");
    }

    #[test]
    fn upsert_with_wrong_dim_errors() {
        let dir = tmp_project("upsert-bad-dim");
        let mut store = VectorStore::open(&dir, 3).unwrap();
        // 故意用 2 维向量(与 store dim=3 不匹配)
        let res = store.upsert_chunks("p", &[(0, "x".to_string(), vec![1.0, 0.0])]);
        assert!(res.is_err());
    }

    // ---- delete ----

    #[test]
    fn delete_by_page_removes_all_chunks_of_page() {
        let dir = tmp_project("delete-page");
        let mut store = VectorStore::open(&dir, 3).unwrap();
        store
            .upsert_chunks(
                "a",
                &[
                    (0, "a0".to_string(), vec3(1.0, 0.0, 0.0)),
                    (1, "a1".to_string(), vec3(0.0, 1.0, 0.0)),
                ],
            )
            .unwrap();
        store
            .upsert_chunks("b", &[(0, "b0".to_string(), vec3(0.0, 0.0, 1.0))])
            .unwrap();
        assert_eq!(store.len(), 3);
        let removed = store.delete_by_page("a");
        assert_eq!(removed, 2);
        assert_eq!(store.len(), 1);
        assert_eq!(store.records[0].page_path, "b");
    }

    // ---- search ----

    #[test]
    fn search_returns_top_k_by_cosine() {
        let dir = tmp_project("search-topk");
        let mut store = VectorStore::open(&dir, 3).unwrap();
        // 4 个 chunk:与 query (1,0,0) 的相似度排序
        store
            .upsert_chunks(
                "p",
                &[
                    (0, "exact".to_string(), vec3(1.0, 0.0, 0.0)),       // score = 1.0
                    (1, "perpendicular".to_string(), vec3(0.0, 1.0, 0.0)), // score = 0.0
                    (2, "half".to_string(), vec3(0.5, 0.5, 0.0)),         // score ≈ 0.707
                    (3, "half2".to_string(), vec3(0.707, 0.707, 0.0)),    // score ≈ 1.0
                ],
            )
            .unwrap();
        let hits = store.search(&vec3(1.0, 0.0, 0.0), 2).unwrap();
        assert_eq!(hits.len(), 2);
        // top-1 应该是 exact (cosine=1.0)
        assert_eq!(hits[0].content, "exact");
        // top-2 应该是 half 或 half2 (cosine 都≈0.707)
        assert!(hits[1].content == "half" || hits[1].content == "half2");
        // 验证 perpendicular (cosine=0.0) 不会出现在 top-2
        assert!(hits.iter().all(|h| h.content != "perpendicular"));
    }

    #[test]
    fn search_with_zero_query_vector_returns_empty() {
        let dir = tmp_project("search-zero");
        let mut store = VectorStore::open(&dir, 3).unwrap();
        store
            .upsert_chunks("p", &[(0, "x".to_string(), vec3(1.0, 0.0, 0.0))])
            .unwrap();
        let hits = store.search(&vec3(0.0, 0.0, 0.0), 10).unwrap();
        assert!(hits.is_empty());
    }

    #[test]
    fn search_with_wrong_dim_errors() {
        let dir = tmp_project("search-bad-dim");
        let store = VectorStore::open(&dir, 3).unwrap();
        // 故意用 2 维 query(与 store dim=3 不匹配)
        let res = store.search(&vec![1.0, 0.0], 10);
        assert!(res.is_err());
    }

    #[test]
    fn search_after_delete_omits_removed_page() {
        let dir = tmp_project("search-after-delete");
        let mut store = VectorStore::open(&dir, 3).unwrap();
        store
            .upsert_chunks(
                "keep",
                &[(0, "k".to_string(), vec3(1.0, 0.0, 0.0))],
            )
            .unwrap();
        store
            .upsert_chunks(
                "drop",
                &[(0, "d".to_string(), vec3(1.0, 0.0, 0.0))],
            )
            .unwrap();
        store.delete_by_page("drop");
        store.flush().unwrap();
        // 重新打开验证持久化也对
        drop(store);
        let store2 = VectorStore::open(&dir, 3).unwrap();
        let hits = store2.search(&vec3(1.0, 0.0, 0.0), 10).unwrap();
        assert!(hits.iter().all(|h| h.page_path != "drop"));
        assert!(hits.iter().any(|h| h.page_path == "keep"));
    }
}
