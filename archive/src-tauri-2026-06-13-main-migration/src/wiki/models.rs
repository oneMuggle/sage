// Wiki data models
use serde::{Deserialize, Serialize};

/// A wiki project - a directory containing raw sources and wiki pages
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WikiProject {
    pub id: String,
    pub name: String,
    pub path: String, // Forward slashes
}

/// A file node in the wiki directory tree
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileNode {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub children: Option<Vec<FileNode>>,
}

/// A wiki page with its content
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WikiPage {
    pub path: String,
    pub content: String,
    pub title: String,
}

/// A search result from wiki full-text search
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub path: String,
    pub title: String,
    pub snippet: String,
    pub score: f64,
}

/// Response from wiki search
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResponse {
    pub results: Vec<SearchResult>,
    pub total: usize,
}

/// Result of ingesting a source document
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestResult {
    pub source_path: String,
    pub wiki_page_path: String,
    pub page_type: String,
}

/// Response from wiki chat
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WikiChatResponse {
    pub answer: String,
    pub citations: Vec<String>, // paths of pages cited
}

// Re-export Graph types from graph module (避免重复定义)
pub use crate::wiki::graph::{GraphData, GraphEdge, GraphNode, SignalType as GraphSignal};
