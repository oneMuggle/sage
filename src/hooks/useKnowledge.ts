import { useState, useMemo } from 'react'

export interface KnowledgeDoc {
  id: string
  title: string
  description: string
  pages: number
  updated_at: string
  category: string
  tags?: string[]
}

// Mock data — replace with real API calls
const MOCK_DOCS: KnowledgeDoc[] = [
  {
    id: 'prd',
    title: '产品需求文档',
    description: 'Sage 核心功能定义、用户故事、交互流程和技术约束',
    pages: 42,
    updated_at: '2026-05-25',
    category: '产品',
  },
  {
    id: 'api-docs',
    title: 'API 接口文档',
    description: '内部 API 网关所有端点的请求/响应格式和鉴权说明',
    pages: 128,
    updated_at: '2026-05-27',
    category: '技术',
  },
  {
    id: 'deploy-guide',
    title: '部署指南',
    description: 'Windows 7 / 10 / 11 环境的部署步骤和故障排查',
    pages: 18,
    updated_at: '2026-05-23',
    category: '运维',
  },
  {
    id: 'memory-arch',
    title: '记忆系统架构',
    description: '本地存储结构、同步策略和冲突解决机制',
    pages: 24,
    updated_at: '2026-05-21',
    category: '技术',
  },
  {
    id: 'ui-spec',
    title: 'UI 设计规范',
    description: '设计令牌、组件库、响应式断点和无障碍指南',
    pages: 36,
    updated_at: '2026-05-26',
    category: '设计',
  },
  {
    id: 'test-data',
    title: '测试数据集',
    description: '用于验证记忆检索和对话质量的样本对话和测试用例',
    pages: 15,
    updated_at: '2026-05-24',
    category: '测试',
  },
]

interface UseKnowledgeReturn {
  docs: KnowledgeDoc[]
  filteredDocs: KnowledgeDoc[]
  searchQuery: string
  setSearchQuery: (q: string) => void
  selectedCategory: string
  setSelectedCategory: (c: string) => void
  categories: string[]
  selectedIds: Set<string>
  toggleSelection: (id: string) => void
  clearSelection: () => void
  isLoading: boolean
}

export function useKnowledge(): UseKnowledgeReturn {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('全部')
  const [selectedIds] = useState(() => new Set<string>())

  const categories = useMemo(() => {
    const cats = new Set(MOCK_DOCS.map((d) => d.category))
    return ['全部', ...Array.from(cats)]
  }, [])

  const filteredDocs = useMemo(() => {
    return MOCK_DOCS.filter((doc) => {
      const matchCategory =
        selectedCategory === '全部' || doc.category === selectedCategory
      const matchSearch =
        !searchQuery ||
        doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        doc.description.toLowerCase().includes(searchQuery.toLowerCase())
      return matchCategory && matchSearch
    })
  }, [searchQuery, selectedCategory])

  const toggleSelection = (id: string) => {
    selectedIds.has(id) ? selectedIds.delete(id) : selectedIds.add(id)
  }

  const clearSelection = () => {
    selectedIds.clear()
  }

  return {
    docs: MOCK_DOCS,
    filteredDocs,
    searchQuery,
    setSearchQuery,
    selectedCategory,
    setSelectedCategory,
    categories,
    selectedIds,
    toggleSelection,
    clearSelection,
    isLoading: false,
  }
}
