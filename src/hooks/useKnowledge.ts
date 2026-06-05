import { useState, useMemo, useEffect } from 'react'

import { knowledgeApi, type KnowledgeDoc as ApiKnowledgeDoc } from '../lib/api'

export interface KnowledgeDoc {
  id: string
  title: string
  description: string
  pages: number
  updated_at: string
  category: string
  tags?: string[]
}

function apiDocToKnowledgeDoc(doc: ApiKnowledgeDoc): KnowledgeDoc {
  return {
    ...doc,
    tags: doc.tags ?? [],
  }
}

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
  error: string | null
}

export function useKnowledge(): UseKnowledgeReturn {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('全部')
  const [selectedIds] = useState(() => new Set<string>())
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Load docs from API on mount
  useEffect(() => {
    let cancelled = false
    const loadDocs = async () => {
      setIsLoading(true)
      setError(null)
      try {
        const apiDocs = await knowledgeApi.list()
        if (!cancelled) {
          setDocs(apiDocs.map(apiDocToKnowledgeDoc))
        }
      } catch {
        if (!cancelled) {
          setError('加载知识库文档失败')
          setDocs([])
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    loadDocs()
    return () => { cancelled = true }
  }, [])

  const categories = useMemo(() => {
    const cats = new Set(docs.map((d) => d.category))
    return ['全部', ...Array.from(cats)]
  }, [docs])

  const filteredDocs = useMemo(() => {
    return docs.filter((doc) => {
      const matchCategory =
        selectedCategory === '全部' || doc.category === selectedCategory
      const matchSearch =
        !searchQuery ||
        doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        doc.description.toLowerCase().includes(searchQuery.toLowerCase())
      return matchCategory && matchSearch
    })
  }, [docs, searchQuery, selectedCategory])

  const toggleSelection = (id: string) => {
    selectedIds.has(id) ? selectedIds.delete(id) : selectedIds.add(id)
  }

  const clearSelection = () => {
    selectedIds.clear()
  }

  return {
    docs,
    filteredDocs,
    searchQuery,
    setSearchQuery,
    selectedCategory,
    setSelectedCategory,
    categories,
    selectedIds,
    toggleSelection,
    clearSelection,
    isLoading,
    error,
  }
}
