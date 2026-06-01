import { describe, expect, test } from 'vitest'
import { buildStoryPayload, defaultStoryForm } from './storyForm'

describe('buildStoryPayload', () => {
  test('builds create-story payload from the compact form', () => {
    const payload = buildStoryPayload({
      ...defaultStoryForm,
      title: '生命倒计时',
      premise: '男主能看到寿命倒计时。',
      characters: '小黑|主角|普通学生\n杰瑞|富商|与主角合作',
      minWords: 600,
      targetWords: 1000,
      maxWords: 1500,
    })

    expect(payload).toMatchObject({
      title: '生命倒计时',
      premise: '男主能看到寿命倒计时。',
      word_count: {
        min_words: 600,
        target_words: 1000,
        max_words: 1500,
      },
    })
    expect(payload.characters).toEqual([
      { name: '小黑', role: '主角', description: '普通学生' },
      { name: '杰瑞', role: '富商', description: '与主角合作' },
    ])
  })
})
