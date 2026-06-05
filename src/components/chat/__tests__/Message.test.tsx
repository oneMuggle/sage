import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Message } from '../Message'
import type { Message as MessageType } from '../../../lib/store'

describe('Message', () => {
  it('renders plain text content', () => {
    const msg: MessageType = {
      id: '1', session_id: 's', role: 'assistant',
      content: '你好！', created_at: 0,
    }
    render(<Message message={msg} />)
    expect(screen.getByText('你好！')).toBeInTheDocument()
  })

  it('renders tool_call indicator', () => {
    const msg: MessageType = {
      id: '1', session_id: 's', role: 'assistant',
      content: '观察中...', created_at: 0,
      tool_calls: [{
        name: 'calculator',
        args: { expression: '1+1' },
        result: '2',
      }],
    }
    const { container } = render(<Message message={msg} />)
    expect(container.textContent).toContain('calculator')
    expect(container.textContent).toContain('2')
  })

  it('applies error style when content starts with [错误', () => {
    const msg: MessageType = {
      id: '1', session_id: 's', role: 'assistant',
      content: '[错误:auth_failed] API Key 无效', created_at: 0,
    }
    const { container } = render(<Message message={msg} />)
    const errorEl = container.querySelector('[data-error="true"]')
    expect(errorEl).toBeInTheDocument()
  })
})
