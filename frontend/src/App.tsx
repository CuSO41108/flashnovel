import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  BookOpen,
  CheckCircle2,
  CirclePause,
  CirclePlay,
  FileText,
  Loader2,
  RefreshCcw,
  Send,
  Square,
  TerminalSquare,
} from 'lucide-react'
import {
  api,
  defaultApiBaseUrl,
  runId,
  storyId,
  streamRunEvents,
  type Artifact,
  type Chapter,
  type MemoryView,
  type Run,
  type RunEvent,
  type Story,
  type WorkspaceSnapshot,
} from './api'
import { pickRunForStory } from './runSelection'
import { compactRunEvents, liveTextFromEvents, shouldRefreshStoryDetails, shouldResetLiveText, shouldStreamRunStatus } from './runEvents'
import { buildStoryPayload, defaultRunForm, defaultStoryForm } from './storyForm'

type Notice = { kind: 'info' | 'error' | 'success'; text: string }

const EVENT_LABELS: Record<string, string> = {
  'run.started': '启动',
  'node.started': '节点开始',
  'node.completed': '节点完成',
  'tool.called': '工具',
  'llm.delta': '输出',
  'llm.usage': '用量',
  'checkpoint.created': '检查点',
  'run.paused': '暂停',
  'run.completed': '完成',
  'run.failed': '失败',
  'run.recovered': '恢复',
}

const NODE_NAMES = ['context', 'plan', 'draft', 'extract', 'check', 'review', 'rewrite', 'commit', 'checkpoint']

function statusClass(status?: string) {
  if (!status) return 'muted'
  if (['completed'].includes(status)) return 'status-good'
  if (['failed', 'canceled'].includes(status)) return 'status-bad'
  if (['awaiting_confirmation', 'paused'].includes(status)) return 'status-wait'
  return 'status-live'
}

function statusLabel(status?: string) {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '生成中',
    awaiting_confirmation: '等待确认',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
    canceled: '已终止',
  }
  return status ? (labels[status] ?? status) : '未启动'
}

function runProgressLabel(run: Run | null, workspace: WorkspaceSnapshot | null, selectedChapter: Chapter | null) {
  const nextChapter = Number(run?.current_chapter ?? workspace?.next_chapter ?? 0) || '-'
  const viewing = selectedChapter ? ` · 正在查看第 ${selectedChapter.chapter} 章` : ''
  if (!run) return `下一章 ${nextChapter}${viewing}`
  if (run.status === 'awaiting_confirmation') return `等待确认 · 下一章 ${nextChapter}${viewing}`
  if (run.status === 'paused') return `已暂停 · 下一章 ${nextChapter}${viewing}`
  if (run.status === 'running' || run.status === 'queued') return `生成中 · 第 ${nextChapter} 章${viewing}`
  if (run.status === 'completed') return `已完成${viewing}`
  if (run.status === 'canceled') return `已终止${viewing}`
  if (run.status === 'failed') return `失败${viewing}`
  return `下一章 ${nextChapter}${viewing}`
}

function canCancelRun(run: Run | null) {
  return Boolean(run && !['completed', 'failed', 'canceled'].includes(String(run.status ?? '')))
}

function eventMessage(event: RunEvent) {
  return String(event.message ?? event.payload?.message ?? event.type)
}

function nodeFromEvent(event: RunEvent) {
  const payloadNode = typeof event.payload?.node === 'string' ? event.payload.node : ''
  if (payloadNode) return payloadNode
  const message = eventMessage(event).toLowerCase()
  return NODE_NAMES.find((node) => message.includes(node)) ?? ''
}

function formatJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2)
}

function formatStoryMeta(story: Story) {
  const created = typeof story.created_at === 'string' ? new Date(story.created_at) : null
  const createdLabel =
    created && !Number.isNaN(created.getTime())
      ? created.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      : '未知时间'
  return `${String(story.genre || story.style || '未分类')} · ${createdLabel} · ${storyId(story).slice(0, 8)}`
}

function chapterArtifacts(artifacts: Artifact[]) {
  return artifacts
    .filter((item) => item.kind === 'chapter' && typeof item.chapter === 'number')
    .sort((a, b) => Number(a.chapter ?? 0) - Number(b.chapter ?? 0))
}

export function App() {
  const [baseUrl, setBaseUrl] = useState(() => localStorage.getItem('flashnovel.apiBaseUrl') || defaultApiBaseUrl())
  const [health, setHealth] = useState<Record<string, unknown> | null>(null)
  const [stories, setStories] = useState<Story[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedStoryId, setSelectedStoryId] = useState('')
  const [workspace, setWorkspace] = useState<WorkspaceSnapshot | null>(null)
  const [memory, setMemory] = useState<MemoryView | null>(null)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [liveText, setLiveText] = useState('')
  const [selectedChapter, setSelectedChapter] = useState<Chapter | null>(null)
  const [activeTab, setActiveTab] = useState<'events' | 'memory' | 'artifacts'>('events')
  const [streamEpoch, setStreamEpoch] = useState(0)
  const [isStreaming, setIsStreaming] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [isBusy, setIsBusy] = useState(false)
  const [showAdvancedStory, setShowAdvancedStory] = useState(false)
  const [showRunSettings, setShowRunSettings] = useState(false)
  const [showVerboseEvents, setShowVerboseEvents] = useState(false)
  const [storyForm, setStoryForm] = useState(defaultStoryForm)
  const [runForm, setRunForm] = useState(defaultRunForm)

  const latestSeqRef = useRef(0)
  const eventLogRef = useRef<HTMLDivElement | null>(null)

  const selectedStory = useMemo(() => stories.find((story) => storyId(story) === selectedStoryId) ?? null, [selectedStoryId, stories])
  const selectedRunId = runId(selectedRun)
  const storyRuns = useMemo(() => runs.filter((run) => String(run.story_id ?? '') === selectedStoryId), [runs, selectedStoryId])
  const chapters = useMemo(() => chapterArtifacts(artifacts), [artifacts])
  const compactedEvents = useMemo(() => compactRunEvents(events), [events])
  const displayedEvents = useMemo(() => {
    if (showVerboseEvents) return events.slice(-200)
    return compactedEvents.visibleEvents
  }, [compactedEvents.visibleEvents, events, showVerboseEvents])
  const hiddenEventCount = showVerboseEvents ? Math.max(0, events.length - displayedEvents.length) : compactedEvents.hiddenCount

  const nodeStates = useMemo(() => {
    return NODE_NAMES.map((node) => {
      const nodeEvents = events.filter((event) => nodeFromEvent(event) === node || event.type.includes(node))
      const last = nodeEvents.at(-1)
      return {
        node,
        state: last ? (last.type.includes('completed') ? 'done' : last.type.includes('started') ? 'active' : 'seen') : 'idle',
      }
    })
  }, [events])

  const setInfo = (text: string) => setNotice({ kind: 'info', text })
  const setError = (error: unknown) => setNotice({ kind: 'error', text: error instanceof Error ? error.message : String(error) })

  const refreshStoriesAndRuns = useCallback(async () => {
    const [healthData, storyData, runData] = await Promise.all([api.health(baseUrl), api.listStories(baseUrl), api.listRuns(baseUrl)])
    setHealth(healthData)
    setStories(storyData.items)
    setRuns(runData.items)
    if (!selectedStoryId && storyData.items.length) {
      setSelectedStoryId(storyId(storyData.items[0]))
    }
  }, [baseUrl, selectedStoryId])

  const refreshStoryDetails = useCallback(
    async (id: string) => {
      if (!id) return
      const [workspaceData, memoryData, artifactData, runData] = await Promise.all([
        api.getWorkspace(baseUrl, id),
        api.getMemory(baseUrl, id),
        api.getArtifacts(baseUrl, id),
        api.listRuns(baseUrl),
      ])
      setWorkspace(workspaceData)
      setMemory(memoryData)
      setArtifacts(artifactData.items)
      setRuns(runData.items)
      const nextRun = pickRunForStory(id, runData.items, workspaceData.latest_run, selectedRun)
      if (runId(nextRun) !== runId(selectedRun)) {
        latestSeqRef.current = 0
        setEvents([])
        setLiveText('')
        setSelectedChapter(null)
      }
      setSelectedRun(nextRun)
    },
    [baseUrl, selectedRun],
  )

  useEffect(() => {
    localStorage.setItem('flashnovel.apiBaseUrl', baseUrl)
  }, [baseUrl])

  useEffect(() => {
    refreshStoriesAndRuns().catch(setError)
  }, [refreshStoriesAndRuns])

  useEffect(() => {
    if (!selectedStoryId) return
    refreshStoryDetails(selectedStoryId).catch(setError)
  }, [refreshStoryDetails, selectedStoryId])

  useEffect(() => {
    eventLogRef.current?.scrollTo({ top: eventLogRef.current.scrollHeight })
  }, [events])

  useEffect(() => {
    if (!selectedRunId) return
    latestSeqRef.current = 0
    setEvents([])
    setLiveText('')
    api
      .getEvents(baseUrl, selectedRunId, 0)
      .then((data) => {
        setEvents(data.items)
        latestSeqRef.current = data.items.reduce((max, item) => Math.max(max, item.seq), 0)
        setLiveText(liveTextFromEvents(data.items))
      })
      .catch(setError)
  }, [baseUrl, selectedRunId])

  useEffect(() => {
    if (!selectedRunId) return
    if (!shouldStreamRunStatus(String(selectedRun?.status ?? '') || undefined)) {
      setIsStreaming(false)
      return
    }
    const controller = new AbortController()
    setIsStreaming(true)
    streamRunEvents(
      baseUrl,
      selectedRunId,
      latestSeqRef.current,
      (event) => {
        latestSeqRef.current = Math.max(latestSeqRef.current, event.seq)
        setEvents((current) => {
          if (current.some((item) => item.seq === event.seq)) return current
          return [...current, event].slice(-500)
        })
        if (event.type === 'llm.delta' && typeof event.payload?.delta === 'string' && event.payload?.channel === 'content') {
          setLiveText((current) => `${current}${event.payload.delta}`)
        }
        if (['chapter.drafted', 'chapter.committed', 'checkpoint.created', 'run.completed', 'run.failed'].includes(event.type)) {
          setLiveText('')
        }
        if (event.type === 'chapter.committed' && selectedStoryId) {
          const chapter = Number(event.payload?.chapter ?? 0)
          if (chapter) {
            api.getChapter(baseUrl, selectedStoryId, chapter).then(setSelectedChapter).catch(setError)
          }
        }
        if (shouldResetLiveText(event)) {
          setLiveText('')
          setSelectedChapter(null)
        }
        if (shouldRefreshStoryDetails(event) && selectedStoryId) {
          refreshStoryDetails(selectedStoryId).catch(setError)
        }
        if (event.type === 'run.failed') {
          setNotice({ kind: 'error', text: eventMessage(event) })
        }
      },
      controller.signal,
    )
      .catch((error) => {
        if (!controller.signal.aborted) setError(error)
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsStreaming(false)
          api.getRun(baseUrl, selectedRunId).then(setSelectedRun).catch(setError)
          if (selectedStoryId) refreshStoryDetails(selectedStoryId).catch(setError)
        }
      })
    return () => controller.abort()
  }, [baseUrl, refreshStoryDetails, selectedRun?.status, selectedRunId, selectedStoryId, streamEpoch])

  async function handleCreateStory() {
    setIsBusy(true)
    try {
      const story = await api.createStory(baseUrl, buildStoryPayload(storyForm))
      await refreshStoriesAndRuns()
      setSelectedStoryId(storyId(story))
      setNotice({ kind: 'success', text: `已创建《${story.title}》` })
    } catch (error) {
      setError(error)
    } finally {
      setIsBusy(false)
    }
  }

  async function handleQuickCreateAndRun() {
    setIsBusy(true)
    try {
      const story = await api.createStory(baseUrl, buildStoryPayload(storyForm))
      const id = storyId(story)
      setSelectedStoryId(id)
      const run = await api.createRun(baseUrl, {
        story_id: id,
        prompt: runForm.prompt,
        max_chapters: Number(runForm.maxChapters) || 5,
        context_budget: Number(runForm.contextBudget) || 0,
        model: runForm.model.trim(),
      })
      await refreshStoriesAndRuns()
      setSelectedRun(run)
      setEvents([])
      setLiveText('')
      latestSeqRef.current = 0
      setStreamEpoch((current) => current + 1)
      setNotice({ kind: 'success', text: `已创建《${story.title}》并启动 Run。` })
    } catch (error) {
      setError(error)
    } finally {
      setIsBusy(false)
    }
  }

  async function handleCreateRun() {
    if (!selectedStoryId) return
    setIsBusy(true)
    try {
      const run = await api.createRun(baseUrl, {
        story_id: selectedStoryId,
        prompt: runForm.prompt,
        max_chapters: Number(runForm.maxChapters) || 5,
        context_budget: Number(runForm.contextBudget) || 0,
        model: runForm.model.trim(),
      })
      setSelectedRun(run)
      setEvents([])
      setLiveText('')
      latestSeqRef.current = 0
      setStreamEpoch((current) => current + 1)
      setNotice({ kind: 'success', text: 'Run 已创建，正在等待事件流。' })
    } catch (error) {
      setError(error)
    } finally {
      setIsBusy(false)
    }
  }

  async function runAction(action: 'pause' | 'resume' | 'cancel' | 'confirm') {
    if (!selectedRunId) return
    setIsBusy(true)
    try {
      const next =
        action === 'pause'
          ? await api.pauseRun(baseUrl, selectedRunId)
          : action === 'resume'
            ? await api.resumeRun(baseUrl, selectedRunId)
            : action === 'confirm'
              ? await api.confirmRun(baseUrl, selectedRunId)
              : await api.cancelRun(baseUrl, selectedRunId)
      setSelectedRun(next)
      setStreamEpoch((current) => current + 1)
      await refreshStoriesAndRuns()
      if (selectedStoryId) await refreshStoryDetails(selectedStoryId)
      const actionLabels = { pause: '暂停', resume: '恢复', confirm: '继续', cancel: '终止' }
      setInfo(`已发送${actionLabels[action]}。`)
    } catch (error) {
      setError(error)
    } finally {
      setIsBusy(false)
    }
  }

  async function openChapter(chapter: number) {
    if (!selectedStoryId) return
    try {
      const data = await api.getChapter(baseUrl, selectedStoryId, chapter)
      setSelectedChapter(data)
    } catch (error) {
      setError(error)
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">FlashNovel Runtime</p>
          <h1>小说 Agent 工作台</h1>
        </div>
        <div className="topbar__right">
          <label className="api-field">
            <span>API</span>
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          </label>
          <button className="icon-button" type="button" onClick={() => refreshStoriesAndRuns().catch(setError)} title="刷新">
            <RefreshCcw size={18} />
          </button>
          <span className={`health ${health ? 'status-good' : 'status-wait'}`}>{health ? 'Backend online' : 'Backend unknown'}</span>
        </div>
      </header>

      {notice ? <div className={`notice notice--${notice.kind}`}>{notice.text}</div> : null}

      <main className="workbench">
        <aside className="panel sidebar">
          <section className="section">
            <div className="section__header">
              <h2>创建 Story</h2>
              <button className="link-button" type="button" onClick={() => setShowAdvancedStory((current) => !current)}>
                {showAdvancedStory ? '收起设置' : '高级设置'}
              </button>
            </div>
            <label className="field">
              <span>标题</span>
              <input value={storyForm.title} onChange={(event) => setStoryForm((current) => ({ ...current, title: event.target.value }))} placeholder="例如：雨夜旧书店" />
            </label>
            <label className="field">
              <span>故事设定</span>
              <textarea value={storyForm.premise} onChange={(event) => setStoryForm((current) => ({ ...current, premise: event.target.value }))} placeholder="一句话或一段话描述故事核心" rows={4} />
            </label>

            <div className="story-quick-actions">
              <button className="primary-button" type="button" disabled={isBusy} onClick={() => void handleQuickCreateAndRun()}>
                <Send size={16} />
                一键创建并生成
              </button>
              <button className="secondary-button" type="button" disabled={isBusy} onClick={() => void handleCreateStory()}>
                <BookOpen size={16} />
                只创建
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={isBusy}
                onClick={() => {
                  setStoryForm(defaultStoryForm)
                  setRunForm(defaultRunForm)
                }}
              >
                <RefreshCcw size={16} />
                恢复样例
              </button>
            </div>

            {showAdvancedStory ? (
              <div className="advanced-fields">
                <div className="split">
                  <label className="field">
                    <span>类型</span>
                    <input value={storyForm.genre} onChange={(event) => setStoryForm((current) => ({ ...current, genre: event.target.value }))} placeholder="例如：悬疑" />
                  </label>
                  <label className="field">
                    <span>风格</span>
                    <input value={storyForm.style} onChange={(event) => setStoryForm((current) => ({ ...current, style: event.target.value }))} placeholder="例如：default" />
                  </label>
                </div>
                <label className="field">
                  <span>人物</span>
                  <textarea value={storyForm.characters} onChange={(event) => setStoryForm((current) => ({ ...current, characters: event.target.value }))} placeholder="每行一个：姓名|定位|描述" rows={4} />
                </label>
                <div className="triple">
                  <label className="field">
                    <span>最少字数</span>
                    <input type="number" value={storyForm.minWords} onChange={(event) => setStoryForm((current) => ({ ...current, minWords: Number(event.target.value) }))} />
                  </label>
                  <label className="field">
                    <span>目标字数</span>
                    <input type="number" value={storyForm.targetWords} onChange={(event) => setStoryForm((current) => ({ ...current, targetWords: Number(event.target.value) }))} />
                  </label>
                  <label className="field">
                    <span>最多字数</span>
                    <input type="number" value={storyForm.maxWords} onChange={(event) => setStoryForm((current) => ({ ...current, maxWords: Number(event.target.value) }))} />
                  </label>
                </div>
              </div>
            ) : (
              <p className="compact-hint">默认使用：悬疑 / default / 800-1200-1800 字 / 示例人物。</p>
            )}
          </section>

          <section className="section section--grow">
            <div className="section__header">
              <h2>故事列表</h2>
              <span>{stories.length} 个</span>
            </div>
            <div className="story-list">
              {stories.map((story) => {
                const id = storyId(story)
                return (
                  <button
                    key={id}
                    className={`story-item ${selectedStoryId === id ? 'is-active' : ''}`}
                    type="button"
                    onClick={() => {
                      latestSeqRef.current = 0
                      setSelectedRun(null)
                      setEvents([])
                      setLiveText('')
                      setSelectedChapter(null)
                      setSelectedStoryId(id)
                    }}
                  >
                    <strong>{story.title}</strong>
                    <span>{formatStoryMeta(story)}</span>
                  </button>
                )
              })}
              {!stories.length ? <p className="empty">暂无故事，先创建一个。</p> : null}
            </div>
          </section>
        </aside>

        <section className="panel center">
          <div className="center__header">
            <div>
              <p className="eyebrow">当前作品</p>
              <h2>{selectedStory?.title ?? '未选择 Story'}</h2>
              <p className="muted">{selectedStory ? String(selectedStory.premise ?? selectedStory.description ?? '') : '选择或创建一个故事后开始生成。'}</p>
            </div>
            <div className="run-status">
              <span className={statusClass(selectedRun?.status)}>{statusLabel(selectedRun?.status)}</span>
              {isStreaming ? <Loader2 className="spin" size={18} /> : null}
            </div>
          </div>

          <section className="run-console">
            <div className="run-console__header">
              <div>
                <h3>生成控制</h3>
                <p className="muted">{selectedRun ? runProgressLabel(selectedRun, workspace, selectedChapter) : '可直接用默认设置启动一次生成。'}</p>
              </div>
              <div className="run-console__header-actions">
                <button className="primary-button run-button" type="button" disabled={!selectedStoryId || isBusy} onClick={() => void handleCreateRun()}>
                  <Send size={16} />
                  创建 Run
                </button>
                <button className="secondary-button" type="button" onClick={() => setShowRunSettings((current) => !current)}>
                  {showRunSettings ? '收起设置' : '生成设置'}
                </button>
              </div>
            </div>

            {showRunSettings ? (
              <div className="run-console__form">
                <label className="field">
                  <span>生成提示</span>
                  <textarea value={runForm.prompt} onChange={(event) => setRunForm((current) => ({ ...current, prompt: event.target.value }))} rows={3} placeholder="从第一章开始写..." />
                </label>
                <div className="run-controls run-controls--settings">
                  <label>
                    <span>章节数</span>
                    <input type="number" min={1} max={20} value={runForm.maxChapters} onChange={(event) => setRunForm((current) => ({ ...current, maxChapters: Number(event.target.value) }))} />
                  </label>
                  <label>
                    <span>上下文预算</span>
                    <input type="number" min={0} step={1000} value={runForm.contextBudget} onChange={(event) => setRunForm((current) => ({ ...current, contextBudget: Number(event.target.value) }))} />
                  </label>
                  <label>
                    <span>模型覆盖</span>
                    <input value={runForm.model} onChange={(event) => setRunForm((current) => ({ ...current, model: event.target.value }))} placeholder="默认读取后端 .env" />
                  </label>
                </div>
              </div>
            ) : null}

            <div className="node-strip">
              {nodeStates.map((item) => (
                <span key={item.node} className={`node-pill node-pill--${item.state}`}>
                  {item.node}
                </span>
              ))}
            </div>

            {selectedRun?.status === 'awaiting_confirmation' ? (
              <div className="checkpoint-callout">
                <strong>已到 5 章检查点</strong>
                <span>继续会从第 {selectedRun.current_chapter ?? 6} 章生成；终止会结束本次 Run，已生成章节会保留。</span>
              </div>
            ) : null}

            <div className="run-actions">
              <button type="button" onClick={() => void runAction('pause')} disabled={!selectedRunId || !['queued', 'running'].includes(String(selectedRun?.status ?? '')) || isBusy}>
                <CirclePause size={16} />
                暂停
              </button>
              <button type="button" onClick={() => void runAction('resume')} disabled={!selectedRunId || selectedRun?.status !== 'paused' || isBusy}>
                <CirclePlay size={16} />
                恢复
              </button>
              <button type="button" onClick={() => void runAction('confirm')} disabled={!selectedRunId || selectedRun?.status !== 'awaiting_confirmation' || isBusy}>
                <CheckCircle2 size={16} />
                继续生成
              </button>
              <button type="button" onClick={() => void runAction('cancel')} disabled={!canCancelRun(selectedRun) || isBusy}>
                <Square size={16} />
                终止本次
              </button>
            </div>
          </section>

          <section className="chapter-pane">
            <div className="chapter-pane__header">
              <div>
                <h2>{selectedChapter ? `第 ${selectedChapter.chapter} 章` : liveText ? '实时生成中' : '章节正文'}</h2>
                <p className="muted">
                  Run {selectedRunId ? selectedRunId.slice(0, 8) : '未创建'} · {runProgressLabel(selectedRun, workspace, selectedChapter)}
                </p>
              </div>
              <div className="chapter-tabs">
                {chapters.map((artifact) => (
                  <button key={artifact.id} type="button" onClick={() => void openChapter(Number(artifact.chapter))}>
                    第 {artifact.chapter} 章
                  </button>
                ))}
              </div>
            </div>
            <textarea
              className="chapter-text"
              readOnly
              value={selectedChapter?.content || liveText}
              placeholder="这里会显示 llm.delta 实时正文；章节 commit 后可以从右上角章节按钮读取最终正文。"
            />
          </section>
        </section>

        <aside className="panel inspector">
          <div className="tabs">
            <button className={activeTab === 'events' ? 'is-active' : ''} type="button" onClick={() => setActiveTab('events')}>
              <TerminalSquare size={16} />
              运行日志
            </button>
            <button className={activeTab === 'memory' ? 'is-active' : ''} type="button" onClick={() => setActiveTab('memory')}>
              <Activity size={16} />
              记忆
            </button>
            <button className={activeTab === 'artifacts' ? 'is-active' : ''} type="button" onClick={() => setActiveTab('artifacts')}>
              <FileText size={16} />
              文件
            </button>
          </div>

          {activeTab === 'events' ? (
            <>
              <div className="event-summary">
                <span>
                  {events.length ? `共 ${events.length} 条，默认收起 ${compactedEvents.hiddenDeltaCount} 条正文流片段。` : '运行日志会在这里出现。'}
                </span>
                <button className="link-button" type="button" onClick={() => setShowVerboseEvents((current) => !current)}>
                  {showVerboseEvents ? '收起细节' : '展开细节'}
                </button>
              </div>
              <div ref={eventLogRef} className="event-log">
                {hiddenEventCount ? <p className="compact-hint">已收起 {hiddenEventCount} 条低层级日志，正文请看左侧章节区域。</p> : null}
                {displayedEvents.map((event) => (
                  <article key={`${event.seq}-${event.type}`} className={`event event--${event.type.replaceAll('.', '-')}`}>
                    <div className="event__top">
                      <span>#{event.seq}</span>
                      <strong>{EVENT_LABELS[event.type] ?? event.type}</strong>
                    </div>
                    <p>{eventMessage(event)}</p>
                    {event.type === 'llm.usage' ? <pre>{formatJson(event.payload.usage)}</pre> : null}
                  </article>
                ))}
                {!events.length ? <p className="empty">运行日志会在这里流式出现。</p> : null}
              </div>
            </>
          ) : null}

          {activeTab === 'memory' ? (
            <div className="json-view">
              <pre>{formatJson(memory)}</pre>
            </div>
          ) : null}

          {activeTab === 'artifacts' ? (
            <div className="artifact-list">
              {artifacts.map((artifact) => (
                <article key={artifact.id} className="artifact">
                  <strong>{artifact.kind}</strong>
                  <span>chapter {artifact.chapter ?? '-'}</span>
                  <code>{artifact.id}</code>
                </article>
              ))}
              {!artifacts.length ? <p className="empty">暂无 artifact。</p> : null}
            </div>
          ) : null}
        </aside>
      </main>
    </div>
  )
}
