import { describe, expect, test } from 'vitest'
import { parseSseBuffer, unwrapEnvelope } from './api'

describe('flashnovel api helpers', () => {
  test('unwrapEnvelope returns data for OK responses', () => {
    expect(unwrapEnvelope<{ value: number }>({ code: 'OK', data: { value: 7 } })).toEqual({ value: 7 })
  })

  test('unwrapEnvelope rejects backend error envelopes', () => {
    expect(() => unwrapEnvelope({ code: 'BAD_REQUEST', message: 'story is busy' })).toThrow('story is busy')
  })

  test('parseSseBuffer parses complete frames and keeps trailing partial frame', () => {
    const buffer = [
      'event: node.started',
      'data: {"seq":1,"type":"node.started","payload":{"message":"draft"}}',
      '',
      'event: llm.delta',
      'data: {"seq":2,"type":"llm.delta","payload":{"delta":"雨夜"}}',
      '',
      'event: llm.delta',
      'data: {"seq"',
    ].join('\n')

    const parsed = parseSseBuffer(buffer)

    expect(parsed.events).toHaveLength(2)
    expect(parsed.events[0].type).toBe('node.started')
    expect(parsed.events[1].payload.delta).toBe('雨夜')
    expect(parsed.rest).toContain('event: llm.delta')
  })
})
