export type ApiEnvelope<T> = {
  code?: string
  data?: T
  message?: string
}

export type Story = {
  id?: string
  story_id?: string
  title: string
  description?: string
  premise?: string
  genre?: string
  style?: string
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

export type CharacterInput = {
  name: string
  role?: string
  description?: string
}

export type CreateStoryPayload = {
  title: string
  premise: string
  genre?: string
  style?: string
  characters?: CharacterInput[]
  word_count?: {
    min_words: number
    target_words: number
    max_words: number
  }
}

export type CreateRunPayload = {
  story_id: string
  prompt: string
  provider?: string
  base_url?: string
  model?: string
  max_chapters?: number
  context_budget?: number
}

export type Run = {
  id?: string
  run_id?: string
  story_id?: string
  status?: string
  current_chapter?: number
  max_chapters?: number
  context_budget?: number
  prompt?: string
  error?: string
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

export type RunEvent = {
  id?: string
  seq: number
  type: string
  message?: string
  payload: Record<string, unknown>
  created_at?: string
  [key: string]: unknown
}

export type Artifact = {
  id: string
  story_id?: string
  run_id?: string
  chapter?: number
  kind?: string
  path?: string
  extension?: string
  created_at?: string
  metadata?: Record<string, unknown>
}

export type Chapter = {
  chapter: number
  content: string
  summary?: Record<string, unknown> | null
  artifact?: Artifact
}

export type WorkspaceSnapshot = {
  story?: Story
  workspace?: Record<string, unknown>
  latest_run?: Run | null
  next_chapter?: number
}

export type MemoryView = {
  artifact?: Record<string, unknown>
  canon?: Record<string, unknown>
  episodic?: Record<string, unknown>
  continuity?: Record<string, unknown>
}

export function defaultApiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://127.0.0.1:8010'
}

export function storyId(story: Story | null | undefined): string {
  return String(story?.story_id ?? story?.id ?? '')
}

export function runId(run: Run | null | undefined): string {
  return String(run?.run_id ?? run?.id ?? '')
}

export function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.code && envelope.code !== 'OK') {
    throw new Error(envelope.message || envelope.code)
  }
  if (!('data' in envelope)) {
    throw new Error(envelope.message || '接口返回缺少 data')
  }
  return envelope.data as T
}

async function readJsonEnvelope<T>(response: Response): Promise<T> {
  const text = await response.text()
  const json = text ? (JSON.parse(text) as ApiEnvelope<T>) : ({ code: 'OK', data: undefined as T } satisfies ApiEnvelope<T>)
  if (!response.ok) {
    throw new Error(json.message || `HTTP ${response.status}`)
  }
  return unwrapEnvelope(json)
}

export async function apiFetch<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  return readJsonEnvelope<T>(response)
}

export function parseSseBuffer(buffer: string): { events: RunEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const frames = normalized.split('\n\n')
  const rest = frames.pop() ?? ''
  const events: RunEvent[] = []

  for (const frame of frames) {
    const data = frame
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data) {
      continue
    }
    events.push(JSON.parse(data) as RunEvent)
  }

  return { events, rest }
}

export async function streamRunEvents(
  baseUrl: string,
  id: string,
  afterSeq: number,
  onEvent: (event: RunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${baseUrl}/runs/${encodeURIComponent(id)}/events/stream?after_seq=${encodeURIComponent(String(afterSeq))}`, {
    headers: { Accept: 'text/event-stream' },
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`事件流连接失败：HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    const parsed = parseSseBuffer(buffer)
    buffer = parsed.rest
    parsed.events.forEach(onEvent)
    if (done) {
      break
    }
  }
}

export const api = {
  health: (baseUrl: string) => apiFetch<Record<string, unknown>>(baseUrl, '/health'),
  listStories: (baseUrl: string) => apiFetch<{ items: Story[] }>(baseUrl, '/stories'),
  createStory: (baseUrl: string, payload: CreateStoryPayload) =>
    apiFetch<Story>(baseUrl, '/stories', { method: 'POST', body: JSON.stringify(payload) }),
  getWorkspace: (baseUrl: string, id: string) => apiFetch<WorkspaceSnapshot>(baseUrl, `/workspaces/${encodeURIComponent(id)}`),
  getMemory: (baseUrl: string, id: string) => apiFetch<MemoryView>(baseUrl, `/workspaces/${encodeURIComponent(id)}/memory`),
  getArtifacts: (baseUrl: string, id: string) => apiFetch<{ items: Artifact[] }>(baseUrl, `/workspaces/${encodeURIComponent(id)}/artifacts`),
  listRuns: (baseUrl: string) => apiFetch<{ items: Run[] }>(baseUrl, '/runs'),
  getRun: (baseUrl: string, id: string) => apiFetch<Run>(baseUrl, `/runs/${encodeURIComponent(id)}`),
  createRun: (baseUrl: string, payload: CreateRunPayload) =>
    apiFetch<Run>(baseUrl, '/runs', { method: 'POST', body: JSON.stringify(payload) }),
  getEvents: (baseUrl: string, id: string, afterSeq = 0) =>
    apiFetch<{ items: RunEvent[] }>(baseUrl, `/runs/${encodeURIComponent(id)}/events?after_seq=${encodeURIComponent(String(afterSeq))}`),
  pauseRun: (baseUrl: string, id: string) => apiFetch<Run>(baseUrl, `/runs/${encodeURIComponent(id)}/pause`, { method: 'POST' }),
  resumeRun: (baseUrl: string, id: string, prompt = '') =>
    apiFetch<Run>(baseUrl, `/runs/${encodeURIComponent(id)}/resume`, { method: 'POST', body: JSON.stringify({ prompt }) }),
  confirmRun: (baseUrl: string, id: string) =>
    apiFetch<Run>(baseUrl, `/runs/${encodeURIComponent(id)}/confirm`, { method: 'POST', body: JSON.stringify({ decision: 'continue' }) }),
  cancelRun: (baseUrl: string, id: string) => apiFetch<Run>(baseUrl, `/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  getChapter: (baseUrl: string, id: string, chapter: number) =>
    apiFetch<Chapter>(baseUrl, `/stories/${encodeURIComponent(id)}/chapters/${encodeURIComponent(String(chapter))}`),
}
