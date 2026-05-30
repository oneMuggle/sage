import type { DiscoveredModel, ModelCapability } from '../types/settings'

interface OpenAIModelInfo {
  id: string
  object: string
  created?: number
  owned_by?: string
}

interface OpenAIModelsResponse {
  object: string
  data: OpenAIModelInfo[]
}

export interface ConnectionTestResult {
  success: boolean
  message: string
  latency: number
}

/**
 * Fetch available models from an OpenAI-compatible endpoint.
 */
export async function fetchModels(
  baseUrl: string,
  apiKey: string
): Promise<DiscoveredModel[]> {
  const normalizedBase = baseUrl.replace(/\/+$/, '')
  const response = await fetch(`${normalizedBase}/models`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
  })

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status}: ${text || response.statusText}`)
  }

  const data: OpenAIModelsResponse = await response.json()
  return data.data.map((m) => ({
    id: m.id,
    capabilities: inferCapabilities(m.id),
    endpointId: '',
  }))
}

/**
 * Test connectivity to an OpenAI-compatible endpoint.
 */
export async function testEndpointConnection(
  baseUrl: string,
  apiKey: string
): Promise<ConnectionTestResult> {
  const start = Date.now()
  try {
    const models = await fetchModels(baseUrl, apiKey)
    return {
      success: true,
      message: `连接成功，发现 ${models.length} 个模型`,
      latency: Date.now() - start,
    }
  } catch (error) {
    return {
      success: false,
      message: `连接失败: ${error instanceof Error ? error.message : String(error)}`,
      latency: Date.now() - start,
    }
  }
}

/**
 * Infer model capabilities from the model ID string.
 */
function inferCapabilities(modelId: string): ModelCapability[] {
  const lower = modelId.toLowerCase()
  const caps: ModelCapability[] = ['chat']

  if (
    lower.includes('vision') ||
    lower.includes('gpt-4o') ||
    lower.includes('gemini') ||
    lower.includes('claude-3') ||
    lower.includes('image')
  ) {
    caps.push('vision')
  }
  if (
    lower.includes('embed') ||
    lower.includes('text-embedding') ||
    lower.includes('vector')
  ) {
    caps.push('embedding')
  }

  return caps
}
