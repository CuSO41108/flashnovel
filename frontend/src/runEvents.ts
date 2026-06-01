import type { RunEvent } from './api'

const COLLAPSED_EVENT_TYPES = new Set(['llm.delta'])

function isContentDelta(event: RunEvent) {
  return event.type === 'llm.delta' && event.payload?.channel === 'content' && typeof event.payload.delta === 'string'
}

function isDraftStart(event: RunEvent) {
  const message = String(event.message ?? event.payload?.message ?? '').toLowerCase()
  return event.type === 'node.started' && message.includes('draft chapter')
}

function isDraftTerminal(event: RunEvent) {
  return event.type === 'chapter.drafted' || event.type === 'chapter.committed' || event.type === 'run.failed'
}

export function liveTextFromEvents(events: RunEvent[]): string {
  let draftStartIndex = -1
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (isDraftStart(events[index])) {
      draftStartIndex = index
      break
    }
  }
  if (draftStartIndex < 0) {
    return ''
  }
  const afterDraftStart = events.slice(draftStartIndex + 1)
  if (afterDraftStart.some(isDraftTerminal)) {
    return ''
  }
  return afterDraftStart.filter(isContentDelta).map((event) => String(event.payload.delta)).join('')
}

export function shouldResetLiveText(event: RunEvent): boolean {
  return isDraftStart(event)
}

export function shouldRefreshStoryDetails(event: RunEvent): boolean {
  return event.type === 'chapter.committed' || event.type === 'checkpoint.created' || event.type === 'run.completed' || event.type === 'run.paused'
}

export function shouldStreamRunStatus(status: string | undefined): boolean {
  return status === 'queued' || status === 'running'
}

export function compactRunEvents(events: RunEvent[], limit = 30): { visibleEvents: RunEvent[]; hiddenCount: number; hiddenDeltaCount: number } {
  const importantEvents = events.filter((event) => !COLLAPSED_EVENT_TYPES.has(event.type))
  const visibleEvents = importantEvents.slice(-limit)
  return {
    visibleEvents,
    hiddenCount: Math.max(0, events.length - visibleEvents.length),
    hiddenDeltaCount: events.filter((event) => event.type === 'llm.delta').length,
  }
}
