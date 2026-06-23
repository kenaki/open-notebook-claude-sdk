// Palette for chat-gallery grouping tags. Class strings are written as literals
// (not built dynamically) so Tailwind's JIT keeps them. A tag with no explicit
// color gets a deterministic auto-color from its name, overridable per notebook
// via the notebook's `chat_tag_colors` map.

export const TAG_COLOR_KEYS = [
  'slate',
  'red',
  'orange',
  'amber',
  'green',
  'teal',
  'blue',
  'violet',
  'pink',
] as const

export type TagColorKey = (typeof TAG_COLOR_KEYS)[number]

interface TagColorStyle {
  // Chip background + text (readable in light and dark).
  chip: string
  // Solid swatch used in the color picker + section dot.
  solid: string
}

const STYLES: Record<TagColorKey, TagColorStyle> = {
  slate: { chip: 'bg-slate-500/15 text-slate-700 dark:text-slate-300', solid: 'bg-slate-500' },
  red: { chip: 'bg-red-500/15 text-red-700 dark:text-red-300', solid: 'bg-red-500' },
  orange: { chip: 'bg-orange-500/15 text-orange-700 dark:text-orange-300', solid: 'bg-orange-500' },
  amber: { chip: 'bg-amber-500/15 text-amber-700 dark:text-amber-300', solid: 'bg-amber-500' },
  green: { chip: 'bg-green-500/15 text-green-700 dark:text-green-300', solid: 'bg-green-500' },
  teal: { chip: 'bg-teal-500/15 text-teal-700 dark:text-teal-300', solid: 'bg-teal-500' },
  blue: { chip: 'bg-blue-500/15 text-blue-700 dark:text-blue-300', solid: 'bg-blue-500' },
  violet: { chip: 'bg-violet-500/15 text-violet-700 dark:text-violet-300', solid: 'bg-violet-500' },
  pink: { chip: 'bg-pink-500/15 text-pink-700 dark:text-pink-300', solid: 'bg-pink-500' },
}

// Stable color picked from the tag name when none is set explicitly.
export function autoTagColorKey(tag: string): TagColorKey {
  let h = 0
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) >>> 0
  return TAG_COLOR_KEYS[h % TAG_COLOR_KEYS.length]
}

// Resolve the effective color key for a tag: explicit notebook override first,
// then the deterministic auto-color.
export function resolveTagColorKey(
  tag: string,
  colorMap: Record<string, string> | undefined
): TagColorKey {
  const explicit = colorMap?.[tag.toLowerCase()]
  if (explicit && (TAG_COLOR_KEYS as readonly string[]).includes(explicit)) {
    return explicit as TagColorKey
  }
  return autoTagColorKey(tag.toLowerCase())
}

export function tagColorStyle(key: TagColorKey): TagColorStyle {
  return STYLES[key]
}
