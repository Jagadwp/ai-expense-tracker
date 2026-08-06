export interface RangePreset {
  label: string
  months?: number
  days?: number
}

export const PRESETS: RangePreset[] = [
  { label: '7D', days: 7 },
  { label: '1M', months: 1 },
  { label: '3M', months: 3 },
  { label: '6M', months: 6 },
  { label: '1Y', months: 12 },
]

export const DEFAULT_PRESET = '1M'

export function toIsoDate(d: Date): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function presetRange(preset: RangePreset, today: Date): { dateFrom: string; dateTo: string } {
  const from = new Date(today)
  if (preset.days) {
    from.setDate(from.getDate() - preset.days)
  } else if (preset.months) {
    from.setMonth(from.getMonth() - preset.months)
  }
  return { dateFrom: toIsoDate(from), dateTo: toIsoDate(today) }
}

/** Month-to-date: from the 1st of the current month through today. */
export function monthToDateRange(today: Date): { dateFrom: string; dateTo: string } {
  const dateFrom = toIsoDate(new Date(today.getFullYear(), today.getMonth(), 1))
  return { dateFrom, dateTo: toIsoDate(today) }
}

/** Full calendar-month range for a "YYYY-MM" value, e.g. "2026-08" -> Aug 1 – Aug 31. */
export function monthRange(yyyyMm: string): { dateFrom: string; dateTo: string } {
  const [year, month] = yyyyMm.split('-').map(Number)
  const dateFrom = toIsoDate(new Date(year, month - 1, 1))
  const dateTo = toIsoDate(new Date(year, month, 0))
  return { dateFrom, dateTo }
}

/** Returns the "YYYY-MM" value if [dateFrom, dateTo] is exactly one full calendar month, else null. */
export function matchedMonth(dateFrom: string, dateTo: string): string | null {
  const [year, month] = dateFrom.split('-').map(Number)
  const range = monthRange(`${year}-${String(month).padStart(2, '0')}`)
  return range.dateFrom === dateFrom && range.dateTo === dateTo ? `${year}-${String(month).padStart(2, '0')}` : null
}

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

export function formatMonthLabel(yyyyMm: string): string {
  const [year, month] = yyyyMm.split('-').map(Number)
  return `${MONTH_NAMES[month - 1]} ${year}`
}
