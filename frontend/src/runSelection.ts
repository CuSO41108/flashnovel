import type { Run } from './api'

export function pickRunForStory(storyId: string, runs: Run[], latestRun: Run | null | undefined, currentRun: Run | null): Run | null {
  const fromList = runs.find((run) => String(run.story_id ?? '') === storyId) ?? null
  const fromWorkspace = latestRun && String(latestRun.story_id ?? '') === storyId ? latestRun : null
  const next = fromList ?? fromWorkspace

  if (!next) {
    return null
  }
  return next
}
