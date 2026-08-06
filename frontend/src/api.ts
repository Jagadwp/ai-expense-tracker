import type {
  CategoryPeriodComparison,
  CategoryTotal,
  CategoryTrendPoint,
  Filters,
  PeriodComparison,
  QaAnswer,
  TransactionDetail,
  TransactionPage,
  TransactionQuery,
  TrendPoint,
} from './types'

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status}`)
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
    throw new Error(`mark-as-transfer failed: ${res.status}`)
  }
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
