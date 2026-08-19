import type {
  CategoryPeriodComparison,
  CategoryTotal,
  CategoryTrendPoint,
  ExtractionSummary,
  Filters,
  PeriodComparison,
  QaAnswer,
  SyncAndExtractResult,
  SyncProgress,
  TransactionDetail,
  TransactionInput,
  TransactionPage,
  TransactionQuery,
  TrendPoint,
} from './types'

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // response body wasn't JSON — fall through to the generic message
  }
  return `HTTP ${res.status}`
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    throw new Error(`${path} failed: ${await errorDetail(res)}`)
  }
  return res.json()
}

async function postJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'POST' })
  if (!res.ok) {
    throw new Error(await errorDetail(res))
  }
  return res.json()
}

function rangeParams(filters: Pick<Filters, 'dateFrom' | 'dateTo'>): URLSearchParams {
  return new URLSearchParams({ date_from: filters.dateFrom, date_to: filters.dateTo })
}

export function fetchTransactions(query: TransactionQuery): Promise<TransactionPage> {
  const params = new URLSearchParams({
    date_from: query.dateFrom,
    date_to: query.dateTo,
    include_transfers: String(query.includeTransfers),
    sort_by: query.sortBy,
    sort_dir: query.sortDir,
    page: String(query.page),
    page_size: String(query.pageSize),
  })
  if (query.category) params.set('category', query.category)
  return getJson(`/api/transactions?${params}`)
}

export function fetchCategories(): Promise<string[]> {
  return getJson('/api/categories')
}

export function fetchAvailableMonths(): Promise<string[]> {
  return getJson('/api/available-months')
}

export function fetchCategoryTotals(range: Pick<Filters, 'dateFrom' | 'dateTo'>): Promise<CategoryTotal[]> {
  return getJson(`/api/summary/category-totals?${rangeParams(range)}`)
}

export function fetchCategoryTotalsToday(): Promise<CategoryTotal[]> {
  return getJson('/api/summary/category-totals-today')
}

export function fetchSpendTrend(range: Pick<Filters, 'dateFrom' | 'dateTo'>): Promise<TrendPoint[]> {
  return getJson(`/api/summary/trend?${rangeParams(range)}`)
}

export function fetchPeriodComparison(range: Pick<Filters, 'dateFrom' | 'dateTo'>): Promise<PeriodComparison> {
  return getJson(`/api/summary/period-comparison?${rangeParams(range)}`)
}

export function fetchCategoryPeriodComparison(
  range: Pick<Filters, 'dateFrom' | 'dateTo'>,
): Promise<CategoryPeriodComparison[]> {
  return getJson(`/api/summary/category-period-comparison?${rangeParams(range)}`)
}

export function fetchCategoryTrend(range: Pick<Filters, 'dateFrom' | 'dateTo'>): Promise<CategoryTrendPoint[]> {
  return getJson(`/api/summary/category-trend?${rangeParams(range)}`)
}

export function fetchTransactionDetail(messageId: string): Promise<TransactionDetail> {
  return getJson(`/api/transactions/${encodeURIComponent(messageId)}`)
}

export async function setIsTransfer(messageId: string, isTransfer: boolean): Promise<void> {
  const res = await fetch(`/api/transactions/${encodeURIComponent(messageId)}/is-transfer`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_transfer: isTransfer }),
  })
  if (!res.ok) {
    throw new Error(await errorDetail(res))
  }
}

export async function createTransaction(input: TransactionInput): Promise<{ message_id: string }> {
  const res = await fetch('/api/transactions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    throw new Error(await errorDetail(res))
  }
  return res.json()
}

export async function updateTransaction(messageId: string, input: TransactionInput): Promise<void> {
  const res = await fetch(`/api/transactions/${encodeURIComponent(messageId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    throw new Error(await errorDetail(res))
  }
}

export async function deleteTransaction(messageId: string): Promise<void> {
  const res = await fetch(`/api/transactions/${encodeURIComponent(messageId)}`, { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(await errorDetail(res))
  }
}

export function syncAndExtract(newerThan: string, limit: number): Promise<SyncAndExtractResult> {
  const params = new URLSearchParams({ newer_than: newerThan, limit: String(limit) })
  return postJson(`/api/sync-and-extract?${params}`)
}

export function runExtraction(limit: number): Promise<ExtractionSummary> {
  return postJson(`/api/extract?limit=${limit}`)
}

export function fetchSyncProgress(): Promise<SyncProgress> {
  return getJson('/api/sync-progress')
}

export async function askQuestion(question: string): Promise<QaAnswer> {
  const res = await fetch('/api/qa/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) {
    throw new Error(`ask failed: ${res.status}`)
  }
  return res.json()
}
