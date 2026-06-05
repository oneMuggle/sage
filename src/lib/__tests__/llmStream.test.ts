import { describe, it, expect } from 'vitest'

import { parseNDJSONStream, type AgentEvent } from '../llmStream'

function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(encoder.encode(c)))
      controller.close()
    },
  })
}

describe('parseNDJSONStream', () => {
  it('parses a complete event per line', async () => {
    const stream = makeStream([
      JSON.stringify({ state: 'thinking', iteration: 0 }) + '\n',
      JSON.stringify({ state: 'done', content: 'hi' }) + '\n',
    ])
    const events: AgentEvent[] = []
    for await (const evt of parseNDJSONStream(stream)) {
      events.push(evt)
    }
    expect(events).toHaveLength(2)
    expect(events[0].state).toBe('thinking')
    expect(events[1].content).toBe('hi')
  })

  it('handles chunked lines split across chunks', async () => {
    // 故意把一行 JSON 从关键字中间劈开，模拟网络分块到达
    const stream = makeStream([
      '{"state":"thinki',
      'ng","iteration":0}\n{"state":"done"}\n',
    ])
    const events: AgentEvent[] = []
    for await (const evt of parseNDJSONStream(stream)) {
      events.push(evt)
    }
    expect(events.length).toBeGreaterThanOrEqual(1)
    expect(events[0].state).toBe('thinking')
    expect(events[1].state).toBe('done')
  })

  it('skips empty lines', async () => {
    const stream = makeStream(['\n', JSON.stringify({ state: 'done' }) + '\n', '\n\n'])
    const events: AgentEvent[] = []
    for await (const evt of parseNDJSONStream(stream)) {
      events.push(evt)
    }
    expect(events).toHaveLength(1)
  })
})
