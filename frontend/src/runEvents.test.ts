import { describe, expect, test } from 'vitest'
import { compactRunEvents, liveTextFromEvents, shouldStreamRunStatus } from './runEvents'
import type { RunEvent } from './api'

function event(seq: number, type: string, message: string, payload: Record<string, unknown> = {}): RunEvent {
  return { seq, type, message, payload }
}

describe('liveTextFromEvents', () => {
  test('uses deltas after the latest draft-start event only', () => {
    const events = [
      event(1, 'node.started', 'draft chapter 1', { chapter: 1 }),
      event(2, 'llm.delta', '第一章', { channel: 'content', delta: '第一章' }),
      event(3, 'chapter.committed', 'chapter 1 committed', { chapter: 1 }),
      event(4, 'node.started', 'draft chapter 2', { chapter: 2 }),
      event(5, 'llm.delta', '第二章', { channel: 'content', delta: '第二章' }),
      event(6, 'llm.delta', '继续', { channel: 'content', delta: '继续' }),
    ]

    expect(liveTextFromEvents(events)).toBe('第二章继续')
  })

  test('returns empty text when the latest draft has already committed', () => {
    const events = [
      event(1, 'node.started', 'draft chapter 1', { chapter: 1 }),
      event(2, 'llm.delta', '第一章', { channel: 'content', delta: '第一章' }),
      event(3, 'chapter.committed', 'chapter 1 committed', { chapter: 1 }),
    ]

    expect(liveTextFromEvents(events)).toBe('')
  })
})

describe('compactRunEvents', () => {
  test('hides llm delta events by default and keeps important events', () => {
    const events = [
      event(1, 'run.started', 'run started'),
      event(2, 'llm.delta', 'a', { channel: 'content', delta: 'a' }),
      event(3, 'llm.delta', 'b', { channel: 'content', delta: 'b' }),
      event(4, 'checkpoint.created', 'checkpoint'),
    ]

    expect(compactRunEvents(events)).toEqual({
      visibleEvents: [events[0], events[3]],
      hiddenCount: 2,
      hiddenDeltaCount: 2,
    })
  })
})

describe('shouldStreamRunStatus', () => {
  test('streams only while a run can still produce new events', () => {
    expect(shouldStreamRunStatus('queued')).toBe(true)
    expect(shouldStreamRunStatus('running')).toBe(true)
    expect(shouldStreamRunStatus('awaiting_confirmation')).toBe(false)
    expect(shouldStreamRunStatus('paused')).toBe(false)
    expect(shouldStreamRunStatus('completed')).toBe(false)
    expect(shouldStreamRunStatus(undefined)).toBe(false)
  })
})
