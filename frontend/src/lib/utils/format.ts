import { formatDistanceToNow } from 'date-fns'
import { getDateLocale } from './date-locale'

export function formatCompactNumber(num: number): string {
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`
  return num.toString()
}

export function formatRelative(date: Date | string, lang: string): string {
  return formatDistanceToNow(new Date(date), {
    addSuffix: true,
    locale: getDateLocale(lang),
  })
}

export function formatAbsolute(date: Date | string, lang: string): string {
  return new Date(date).toLocaleString(lang)
}
