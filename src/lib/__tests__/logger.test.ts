import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { logger } from '../logger'

describe('logger', () => {
  beforeEach(() => {
    vi.spyOn(console, 'debug').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not log when disabled', () => {
    logger.setEnabled(false)
    logger.info('REQ-123', 'test', { foo: 'bar' })
    expect(console.info).not.toHaveBeenCalled()
  })

  it('logs with request_id prefix when enabled', () => {
    logger.setEnabled(true)
    logger.info('REQ-123', 'useChat.send', { message: 'hello' })
    expect(console.info).toHaveBeenCalledWith(
      '[REQ-123] [useChat.send]',
      { message: 'hello' }
    )
  })

  it('logs error level', () => {
    logger.setEnabled(true)
    logger.error('REQ-456', 'failed', new Error('boom'))
    expect(console.error).toHaveBeenCalled()
  })
})
