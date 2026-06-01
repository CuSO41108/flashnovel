import { describe, expect, test } from 'vitest'
import { pickRunForStory } from './runSelection'

describe('pickRunForStory', () => {
  test('clears a stale selected run when the current story has no run', () => {
    const staleRun = { run_id: 'old-run', story_id: 'old-story', status: 'failed' }

    expect(pickRunForStory('new-story', [], null, staleRun)).toBeNull()
  })

  test('uses the latest run that belongs to the selected story', () => {
    const matchingRun = { run_id: 'new-run', story_id: 'new-story', status: 'running' }
    const staleRun = { run_id: 'old-run', story_id: 'old-story', status: 'failed' }

    expect(pickRunForStory('new-story', [staleRun, matchingRun], null, staleRun)).toBe(matchingRun)
  })

  test('refreshes a selected run when the same run id has newer status', () => {
    const staleRun = { run_id: 'run-1', story_id: 'story-1', status: 'running', current_chapter: 2 }
    const freshRun = { run_id: 'run-1', story_id: 'story-1', status: 'awaiting_confirmation', current_chapter: 6 }

    expect(pickRunForStory('story-1', [freshRun], null, staleRun)).toBe(freshRun)
  })
})
