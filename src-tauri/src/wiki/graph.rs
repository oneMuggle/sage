// Wiki 4-signal 知识图谱
//
// 设计要点:
// - 扫描 wiki/ 目录所有 .md,解析 frontmatter + 提取 wikilinks
// - 4-signal 边权重 (对齐 llm_wiki):
//     DirectLink (×3.0)  : [[wikilink]] 出现一次 +3.0
//     SourceOverlap (×4.0): 两页 sources:[] 共享数 / 总数 × 4.0
//     TypeAffinity (×1.0) : 同 type 字段 +1.0
//     Adamic-Adar         : 留 TODO
// - 节点用 file_path 作 id
// - 缓存到 .llm-wiki/graph-cache.json (Phase 5.3)

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::wiki::frontmatter::{extract_wikilinks, parse as parse_frontmatter};

// ============================================================================
// 类型
// ============================================================================

/// 边类型(4-signal 中的 1 种)
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SignalType {
    /// [[wikilink]] 出现
    DirectLink,
    /// 两页 sources:[] 共享
    SourceOverlap,
    /// 同 type 字段
    TypeAffinity,
}

impl SignalType {
    /// 默认权重系数
    pub fn weight(self) -> f32 {
        match self {
            SignalType::DirectLink => 3.0,
            SignalType::SourceOverlap => 4.0,
            SignalType::TypeAffinity => 1.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GraphNode {
    /// 唯一 ID(wiki 内相对路径,如 `wiki/sources/albert-einstein.md`)
    pub id: String,
    /// 显示 label (frontmatter title 或文件名)
    pub label: String,
    /// frontmatter type 字段(source/entity/concept/...)
    pub page_type: Option<String>,
    /// frontmatter sources:[] 字段
    pub sources: Vec<String>,
    /// 原始 wikilink 列表(从 frontmatter + body 提取的)
    pub wikilinks: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GraphEdge {
    pub source: String,
    pub target: String,
    pub signal: SignalType,
    pub weight: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct GraphData {
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
}

// ============================================================================
// 图构建
// ============================================================================

/// 扫整个 wiki 目录,构建 GraphData
pub fn build_graph(project_root: &Path) -> Result<GraphData, String> {
    let wiki_dir = project_root.join("wiki");
    if !wiki_dir.exists() {
        return Ok(GraphData::default());
    }

    // 1. 收集所有 .md
    let mut nodes: Vec<GraphNode> = Vec::new();
    let mut md_files: Vec<PathBuf> = Vec::new();
    collect_md_files(&wiki_dir, &mut md_files);

    for path in &md_files {
        if let Ok(content) = fs::read_to_string(path) {
            // 跳过 index.md / log.md(元数据)
            let file_name = path
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            if file_name == "index.md" || file_name == "log.md" {
                continue;
            }
            let parsed = parse_frontmatter(&content);
            let rel = path
                .strip_prefix(project_root)
                .unwrap_or(path)
                .to_string_lossy()
                .replace('\\', "/");
            let label = parsed.frontmatter.title.clone().unwrap_or_else(|| {
                path.file_stem()
                    .map(|s| s.to_string_lossy().to_string())
                    .unwrap_or_else(|| rel.clone())
            });
            let wikilinks = {
                let mut all_links = parsed.frontmatter.related.clone();
                all_links.extend(extract_wikilinks(&parsed.body));
                all_links.sort();
                all_links.dedup();
                all_links
            };
            nodes.push(GraphNode {
                id: rel,
                label,
                page_type: parsed.frontmatter.page_type,
                sources: parsed.frontmatter.sources,
                wikilinks,
            });
        }
    }

    // 2. 索引: id → &GraphNode
    let by_id: HashMap<String, &GraphNode> =
        nodes.iter().map(|n| (n.id.clone(), n)).collect();

    // 3. 构建边(4-signal)
    let mut edges: Vec<GraphEdge> = Vec::new();
    let mut edge_dedup: HashSet<(String, String, SignalType)> = HashSet::new();

    // 3.1 DirectLink
    for node in &nodes {
        for link in &node.wikilinks {
            if let Some(target_id) = resolve_wikilink(link, &by_id) {
                if target_id != node.id {
                    add_edge(
                        &mut edges,
                        &mut edge_dedup,
                        &node.id,
                        &target_id,
                        SignalType::DirectLink,
                    );
                }
            }
        }
    }

    // 3.2 SourceOverlap
    for i in 0..nodes.len() {
        for j in (i + 1)..nodes.len() {
            let a = &nodes[i];
            let b = &nodes[j];
            if a.sources.is_empty() || b.sources.is_empty() {
                continue;
            }
            let a_set: HashSet<&str> = a.sources.iter().map(String::as_str).collect();
            let b_set: HashSet<&str> = b.sources.iter().map(String::as_str).collect();
            let shared = a_set.intersection(&b_set).count();
            if shared == 0 {
                continue;
            }
            let max = a.sources.len().max(b.sources.len());
            let weight = (shared as f32 / max as f32) * SignalType::SourceOverlap.weight();
            for (s, t) in [(&a.id, &b.id), (&b.id, &a.id)] {
                if edge_dedup.insert((s.clone(), t.clone(), SignalType::SourceOverlap)) {
                    edges.push(GraphEdge {
                        source: s.clone(),
                        target: t.clone(),
                        signal: SignalType::SourceOverlap,
                        weight,
                    });
                }
            }
        }
    }

    // 3.3 TypeAffinity
    let mut by_type: HashMap<String, Vec<String>> = HashMap::new();
    for n in &nodes {
        if let Some(t) = &n.page_type {
            by_type.entry(t.clone()).or_default().push(n.id.clone());
        }
    }
    for ids in by_type.values() {
        for i in 0..ids.len() {
            for j in (i + 1)..ids.len() {
                for (s, t) in [(&ids[i], &ids[j]), (&ids[j], &ids[i])] {
                    if edge_dedup.insert((s.clone(), t.clone(), SignalType::TypeAffinity)) {
                        edges.push(GraphEdge {
                            source: s.clone(),
                            target: t.clone(),
                            signal: SignalType::TypeAffinity,
                            weight: SignalType::TypeAffinity.weight(),
                        });
                    }
                }
            }
        }
    }

    Ok(GraphData { nodes, edges })
}

/// 把 wikilink 文本解析为 node id
/// 策略:按 label 精确 → 按 id 精确 → 按 slug 模糊
fn resolve_wikilink(
    link: &str,
    by_id: &HashMap<String, &GraphNode>,
) -> Option<String> {
    for n in by_id.values() {
        if n.label == link {
            return Some(n.id.clone());
        }
    }
    if by_id.contains_key(link) {
        return Some(link.to_string());
    }
    let link_slug = slugify_label(link);
    for n in by_id.values() {
        if slugify_label(&n.label) == link_slug {
            return Some(n.id.clone());
        }
    }
    None
}

fn slugify_label(s: &str) -> String {
    s.to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { '-' })
        .collect::<String>()
        .split('-')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("-")
}

fn add_edge(
    edges: &mut Vec<GraphEdge>,
    dedup: &mut HashSet<(String, String, SignalType)>,
    from: &str,
    to: &str,
    signal: SignalType,
) {
    if dedup.insert((from.to_string(), to.to_string(), signal)) {
        edges.push(GraphEdge {
            source: from.to_string(),
            target: to.to_string(),
            signal,
            weight: signal.weight(),
        });
    }
}

fn collect_md_files(dir: &Path, out: &mut Vec<PathBuf>) {
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.filter_map(|e| e.ok()) {
            let p = entry.path();
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with('.') {
                continue;
            }
            if p.is_dir() {
                collect_md_files(&p, out);
            } else if p.extension().and_then(|s| s.to_str()) == Some("md") {
                out.push(p);
            }
        }
    }
}

// ============================================================================
// Relevance 2-hop 扩散
// ============================================================================

/// 从 query 出发,BFS 2 跳,边权重累乘 × decay^hop
///
/// 返回: node_id → score(降序排列的 vector)
pub fn relevance(query: &str, graph: &GraphData, k_hops: u32) -> Vec<(String, f32)> {
    relevance_with_decay(query, graph, k_hops, 0.5)
}

pub fn relevance_with_decay(
    query: &str,
    graph: &GraphData,
    k_hops: u32,
    decay: f32,
) -> Vec<(String, f32)> {
    let q_lower = query.to_lowercase();

    // 1. 找 seeds:label 或 id 包含 query
    let seeds: Vec<String> = graph
        .nodes
        .iter()
        .filter(|n| {
            n.label.to_lowercase().contains(&q_lower)
                || n.id.to_lowercase().contains(&q_lower)
        })
        .map(|n| n.id.clone())
        .collect();

    if seeds.is_empty() {
        return Vec::new();
    }

    // 2. BFS
    let mut scores: HashMap<String, f32> = HashMap::new();
    let mut current: Vec<(String, f32)> = seeds
        .iter()
        .map(|s| {
            scores.insert(s.clone(), 1.0);
            (s.clone(), 1.0)
        })
        .collect();

    for hop in 0..k_hops {
        let mut next: Vec<(String, f32)> = Vec::new();
        for (node_id, score) in &current {
            for edge in graph.edges.iter().filter(|e| e.source == *node_id) {
                let new_score = score * edge.weight * decay;
                let existing = scores.get(&edge.target).copied().unwrap_or(0.0);
                if new_score > existing {
                    scores.insert(edge.target.clone(), new_score);
                    if hop + 1 < k_hops {
                        next.push((edge.target.clone(), new_score));
                    }
                }
            }
        }
        if next.is_empty() {
            break;
        }
        current = next;
    }

    let mut out: Vec<(String, f32)> = scores.into_iter().collect();
    out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    out
}

/// 从已知 seed 节点出发扩散(不从 query 推断)
pub fn relevance_from_seeds(
    seed_ids: &[String],
    graph: &GraphData,
    k_hops: u32,
) -> Vec<(String, f32)> {
    relevance_from_seeds_with_decay(seed_ids, graph, k_hops, 0.5)
}

pub fn relevance_from_seeds_with_decay(
    seed_ids: &[String],
    graph: &GraphData,
    k_hops: u32,
    decay: f32,
) -> Vec<(String, f32)> {
    let mut scores: HashMap<String, f32> = HashMap::new();
    let mut current: Vec<(String, f32)> = seed_ids
        .iter()
        .map(|s| {
            scores.insert(s.clone(), 1.0);
            (s.clone(), 1.0)
        })
        .collect();

    for hop in 0..k_hops {
        let mut next: Vec<(String, f32)> = Vec::new();
        for (node_id, score) in &current {
            for edge in graph.edges.iter().filter(|e| e.source == *node_id) {
                let new_score = score * edge.weight * decay;
                let existing = scores.get(&edge.target).copied().unwrap_or(0.0);
                if new_score > existing {
                    scores.insert(edge.target.clone(), new_score);
                    if hop + 1 < k_hops {
                        next.push((edge.target.clone(), new_score));
                    }
                }
            }
        }
        if next.is_empty() {
            break;
        }
        current = next;
    }

    let mut out: Vec<(String, f32)> = scores.into_iter().collect();
    out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    out
}

// ============================================================================
// 缓存 + get_graph 入口
// ============================================================================

/// 计算 wiki/ 目录所有 .md 的 mtime 签名(粗粒度:拼接 mtime + path)
fn compute_mtime_signature(project_root: &Path) -> String {
    let wiki_dir = project_root.join("wiki");
    let mut files: Vec<PathBuf> = Vec::new();
    collect_md_files(&wiki_dir, &mut files);
    let mut parts: Vec<String> = Vec::new();
    for f in files {
        let mtime = fs::metadata(&f)
            .and_then(|m| m.modified())
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_nanos().to_string())
            .unwrap_or_default();
        parts.push(format!("{}:{}", f.display(), mtime));
    }
    parts.join("|")
}

fn cache_path(project_root: &Path) -> PathBuf {
    project_root.join(".llm-wiki/graph-cache.json")
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CacheFile {
    mtime_sig: String,
    data: GraphData,
}

fn read_graph_cache(project_root: &Path) -> Option<GraphData> {
    let p = cache_path(project_root);
    if !p.exists() {
        return None;
    }
    let body = fs::read_to_string(&p).ok()?;
    let cache: CacheFile = serde_json::from_str(&body).ok()?;
    let current_sig = compute_mtime_signature(project_root);
    if cache.mtime_sig != current_sig {
        return None;
    }
    Some(cache.data)
}

fn write_graph_cache(project_root: &Path, data: &GraphData) -> Result<(), String> {
    let p = cache_path(project_root);
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("创建 .llm-wiki 失败: {}", e))?;
    }
    let cache = CacheFile {
        mtime_sig: compute_mtime_signature(project_root),
        data: data.clone(),
    };
    let json = serde_json::to_string_pretty(&cache)
        .map_err(|e| format!("序列化 graph cache 失败: {}", e))?;
    let tmp = p.with_extension("json.tmp");
    fs::write(&tmp, json).map_err(|e| format!("写 graph cache 失败: {}", e))?;
    fs::rename(&tmp, &p).map_err(|e| format!("rename graph cache 失败: {}", e))?;
    Ok(())
}

/// 获取 graph(带缓存),可选 query 过滤
pub fn get_graph_cached(
    project_root: &Path,
    query: Option<&str>,
    limit: usize,
) -> Result<GraphData, String> {
    let mut data = if let Some(cached) = read_graph_cache(project_root) {
        cached
    } else {
        let built = build_graph(project_root)?;
        write_graph_cache(project_root, &built)?;
        built
    };

    // 如果有 query,按 relevance 排序 + 过滤到 top-k
    if let Some(q) = query.filter(|s| !s.trim().is_empty()) {
        let scored = relevance(q, &data, 2);
        let keep: HashSet<String> = scored
            .into_iter()
            .take(limit.max(50)) // 至少保留 50 个相关节点
            .map(|(id, _)| id)
            .collect();
        if !keep.is_empty() {
            data.nodes.retain(|n| keep.contains(&n.id));
            data.edges.retain(|e| keep.contains(&e.source) && keep.contains(&e.target));
        }
    }

    Ok(data)
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use std::fs;

    fn tmp_project(name: &str) -> PathBuf {
        let dir = env::temp_dir().join(format!("sage-wiki-graph-test-{}-{}", name, std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write_page(project: &Path, rel_path: &str, content: &str) {
        let full = project.join(rel_path);
        fs::create_dir_all(full.parent().unwrap()).unwrap();
        fs::write(full, content).unwrap();
    }

    #[test]
    fn signal_weights_match_design() {
        assert_eq!(SignalType::DirectLink.weight(), 3.0);
        assert_eq!(SignalType::SourceOverlap.weight(), 4.0);
        assert_eq!(SignalType::TypeAffinity.weight(), 1.0);
    }

    #[test]
    fn slugify_label_basic() {
        assert_eq!(slugify_label("Albert Einstein"), "albert-einstein");
        assert_eq!(slugify_label("Theory of Relativity"), "theory-of-relativity");
    }

    #[test]
    fn slugify_label_chinese_kept() {
        assert_eq!(slugify_label("爱因斯坦"), "爱因斯坦");
    }

    #[test]
    fn build_graph_empty_when_no_wiki_dir() {
        let dir = tmp_project("empty");
        let g = build_graph(&dir).unwrap();
        assert!(g.nodes.is_empty());
        assert!(g.edges.is_empty());
    }

    #[test]
    fn build_graph_single_page_one_node() {
        let dir = tmp_project("single");
        write_page(
            &dir,
            "wiki/sources/a.md",
            "---\ntitle: A\ntype: source\nsources: [raw/x.pdf]\n---\n\nbody",
        );
        let g = build_graph(&dir).unwrap();
        assert_eq!(g.nodes.len(), 1);
        assert_eq!(g.nodes[0].id, "wiki/sources/a.md");
        assert_eq!(g.nodes[0].label, "A");
        assert_eq!(g.nodes[0].page_type.as_deref(), Some("source"));
        assert!(g.edges.is_empty());
    }

    #[test]
    fn build_graph_direct_link_between_two_pages() {
        let dir = tmp_project("direct-link");
        write_page(
            &dir,
            "wiki/sources/a.md",
            "---\ntitle: Albert Einstein\ntype: entity\n---\n\n# Albert\n\nsee [[Theory of Relativity]]",
        );
        write_page(
            &dir,
            "wiki/concepts/b.md",
            "---\ntitle: Theory of Relativity\ntype: concept\n---\n\nbody",
        );
        let g = build_graph(&dir).unwrap();
        assert_eq!(g.nodes.len(), 2);
        let direct_edges: Vec<&GraphEdge> = g
            .edges
            .iter()
            .filter(|e| e.signal == SignalType::DirectLink)
            .collect();
        assert_eq!(direct_edges.len(), 1);
        assert_eq!(direct_edges[0].source, "wiki/sources/a.md");
        assert_eq!(direct_edges[0].target, "wiki/concepts/b.md");
        assert_eq!(direct_edges[0].weight, 3.0);
    }

    #[test]
    fn build_graph_skips_index_and_log() {
        let dir = tmp_project("skip-index");
        write_page(&dir, "wiki/index.md", "# Wiki Index");
        write_page(&dir, "wiki/log.md", "# Wiki Log");
        write_page(&dir, "wiki/a.md", "---\ntitle: A\n---\nbody");
        let g = build_graph(&dir).unwrap();
        assert_eq!(g.nodes.len(), 1);
        assert_eq!(g.nodes[0].id, "wiki/a.md");
    }

    #[test]
    fn build_graph_source_overlap_with_shared_source() {
        let dir = tmp_project("source-overlap");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: A\ntype: source\nsources: [raw/x.pdf]\n---\nbody",
        );
        write_page(
            &dir,
            "wiki/b.md",
            "---\ntitle: B\ntype: source\nsources: [raw/x.pdf, raw/y.pdf]\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let overlap_edges: Vec<&GraphEdge> = g
            .edges
            .iter()
            .filter(|e| e.signal == SignalType::SourceOverlap)
            .collect();
        // 双向 = 2 边
        assert_eq!(overlap_edges.len(), 2);
        // weight = 1 / max(1, 2) * 4.0 = 2.0
        assert!((overlap_edges[0].weight - 2.0).abs() < 1e-6);
    }

    #[test]
    fn build_graph_no_source_overlap_when_disjoint() {
        let dir = tmp_project("disjoint");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: A\nsources: [raw/x.pdf]\n---\nbody",
        );
        write_page(
            &dir,
            "wiki/b.md",
            "---\ntitle: B\nsources: [raw/y.pdf]\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let overlap = g
            .edges
            .iter()
            .filter(|e| e.signal == SignalType::SourceOverlap)
            .count();
        assert_eq!(overlap, 0);
    }

    #[test]
    fn build_graph_type_affinity_between_same_type() {
        let dir = tmp_project("type-aff");
        write_page(&dir, "wiki/a.md", "---\ntitle: A\ntype: entity\n---\nbody");
        write_page(&dir, "wiki/b.md", "---\ntitle: B\ntype: entity\n---\nbody");
        write_page(&dir, "wiki/c.md", "---\ntitle: C\ntype: concept\n---\nbody");
        let g = build_graph(&dir).unwrap();
        let aff_edges: Vec<&GraphEdge> = g
            .edges
            .iter()
            .filter(|e| e.signal == SignalType::TypeAffinity)
            .collect();
        // a↔b 同 entity → 2 边(双向)
        assert_eq!(aff_edges.len(), 2);
        assert!(aff_edges.iter().all(|e| e.weight == 1.0));
    }

    #[test]
    fn build_graph_combines_all_signals() {
        let dir = tmp_project("combined");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: A\ntype: source\nsources: [raw/shared.pdf]\n---\n# A\n\nsee [[B]]",
        );
        write_page(
            &dir,
            "wiki/b.md",
            "---\ntitle: B\ntype: source\nsources: [raw/shared.pdf]\n---\n# B",
        );
        let g = build_graph(&dir).unwrap();
        // DirectLink: a→b 1 边
        // SourceOverlap: a↔b 2 边
        // TypeAffinity: a↔b 2 边
        // 共 5 边
        assert_eq!(g.edges.len(), 5);
    }

    #[test]
    fn resolve_wikilink_by_label() {
        let dir = tmp_project("resolve-label");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: Albert Einstein\ntype: entity\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let by_id: HashMap<String, &GraphNode> =
            g.nodes.iter().map(|n| (n.id.clone(), n)).collect();
        let resolved = resolve_wikilink("Albert Einstein", &by_id);
        assert_eq!(resolved.as_deref(), Some("wiki/a.md"));
    }

    #[test]
    fn resolve_wikilink_case_insensitive_via_slug() {
        let dir = tmp_project("resolve-slug");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: Albert Einstein\ntype: entity\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let by_id: HashMap<String, &GraphNode> =
            g.nodes.iter().map(|n| (n.id.clone(), n)).collect();
        let resolved = resolve_wikilink("albert einstein", &by_id);
        assert_eq!(resolved.as_deref(), Some("wiki/a.md"));
    }

    #[test]
    fn resolve_wikilink_returns_none_for_unknown() {
        let dir = tmp_project("resolve-none");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: A\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let by_id: HashMap<String, &GraphNode> =
            g.nodes.iter().map(|n| (n.id.clone(), n)).collect();
        let resolved = resolve_wikilink("Nonexistent", &by_id);
        assert!(resolved.is_none());
    }

    // ---- relevance ----

    #[test]
    fn relevance_no_seeds_returns_empty() {
        let dir = tmp_project("rel-empty");
        let g = build_graph(&dir).unwrap();
        let r = relevance("nonexistent", &g, 2);
        assert!(r.is_empty());
    }

    #[test]
    fn relevance_single_seed() {
        let dir = tmp_project("rel-single");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: Albert Einstein\ntype: entity\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let r = relevance("einstein", &g, 2);
        assert_eq!(r.len(), 1);
        let first = r.first().unwrap();
        assert_eq!(first.0, "wiki/a.md");
        assert!((first.1 - 1.0).abs() < 1e-6);
    }

    #[test]
    fn relevance_2hop_decay() {
        // a → b (DirectLink 3.0) → c
        // a 1.0, b = 1.0 * 3.0 * 0.5 = 1.5, c = 1.5 * ? * 0.5
        let dir = tmp_project("rel-2hop");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: Einstein\ntype: entity\n---\nbody\n\nsee [[Relativity]]",
        );
        write_page(
            &dir,
            "wiki/b.md",
            "---\ntitle: Relativity\ntype: concept\n---\nbody\n\nsee [[Energy]]",
        );
        write_page(
            &dir,
            "wiki/c.md",
            "---\ntitle: Energy\ntype: concept\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let r = relevance("einstein", &g, 2);
        assert_eq!(r.len(), 3);
        // a=1.0 (seed)
        // b=1.0 * 3.0 * 0.5 = 1.5
        // c=1.5 * 3.0 * 0.5 = 2.25
        let by_id: HashMap<String, f32> = r.iter().cloned().collect();
        assert!((by_id["wiki/a.md"] - 1.0).abs() < 1e-6);
        assert!((by_id["wiki/b.md"] - 1.5).abs() < 1e-6);
        assert!((by_id["wiki/c.md"] - 2.25).abs() < 1e-6);
    }

    #[test]
    fn relevance_k_hops_0_returns_seeds_only() {
        let dir = tmp_project("rel-0hop");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: A\n---\nbody\n\nsee [[B]]",
        );
        write_page(
            &dir,
            "wiki/b.md",
            "---\ntitle: B\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let r = relevance("A", &g, 0);
        assert_eq!(r.len(), 1);
        assert_eq!(r.first().unwrap().0, "wiki/a.md");
    }

    #[test]
    fn relevance_from_seeds_function() {
        let dir = tmp_project("rel-seeds");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: A\n---\nbody\n\nsee [[B]]",
        );
        write_page(
            &dir,
            "wiki/b.md",
            "---\ntitle: B\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let r = relevance_from_seeds(&["wiki/b.md".to_string()], &g, 1);
        // 1 跳,b 是 seed,无出边
        assert_eq!(r.len(), 1);
        assert_eq!(r.first().unwrap().0, "wiki/b.md");
    }

    #[test]
    fn relevance_results_sorted_desc() {
        let dir = tmp_project("rel-sort");
        write_page(
            &dir,
            "wiki/a.md",
            "---\ntitle: Seed\n---\nbody",
        );
        write_page(
            &dir,
            "wiki/b.md",
            "---\ntitle: Other\n---\nbody",
        );
        let g = build_graph(&dir).unwrap();
        let r = relevance("seed", &g, 1);
        // 第 0 个应该是 score 最高的(seed = 1.0)
        assert!(r.first().unwrap().1 >= 1.0);
    }
}
