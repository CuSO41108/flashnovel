import type { CreateStoryPayload } from './api'

export type StoryFormState = {
  title: string
  premise: string
  genre: string
  style: string
  characters: string
  minWords: number
  targetWords: number
  maxWords: number
}

export type RunFormState = {
  prompt: string
  maxChapters: number
  contextBudget: number
  model: string
}

export const defaultStoryForm: StoryFormState = {
  title: '生命倒计时',
  premise: '男主小黑发现，自己可以看到每个人头顶上寿命的倒计时，一场惊心动魄的交易开启，他和身边的人很快陷入了麻烦之中',
  genre: '悬疑',
  style: 'default',
  characters: '小黑|主角|普通学生，谨慎敏感，擅长从身边事物里寻找线索。\n杰瑞|富商|与小黑互相试探后合作。',
  minWords: 800,
  targetWords: 1200,
  maxWords: 1800,
}

export const defaultRunForm: RunFormState = {
  prompt: '从第一章开始写：小黑第一次看到倒计时，交易诱因出现，结尾留下强悬念。',
  maxChapters: 5,
  contextBudget: 20000,
  model: '',
}

export function parseCharacters(text: string): CreateStoryPayload['characters'] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name = '', role = '', description = ''] = line.split('|').map((part) => part.trim())
      return { name, role, description }
    })
    .filter((item) => item.name)
}

export function buildStoryPayload(form: StoryFormState): CreateStoryPayload {
  return {
    title: form.title,
    premise: form.premise,
    genre: form.genre,
    style: form.style || 'default',
    characters: parseCharacters(form.characters),
    word_count: {
      min_words: Number(form.minWords) || 800,
      target_words: Number(form.targetWords) || 1200,
      max_words: Number(form.maxWords) || 1800,
    },
  }
}
