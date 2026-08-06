export interface Transaction {
  message_id: string
  date: string | null
  merchant: string | null
  category: string | null
  amount: number | null
  payment_method: string | null
  is_transfer: boolean
}

export interface TransactionDetail extends Transaction {
  raw_subject: string | null
  raw_from: string | null
  raw_body: string | null
}

export interface CategoryTotal {
  category: string
  total: number
}

export interface TrendPoint {
  date: string
  total: number
}

export interface PeriodComparison {
  current_total: number
  previous_total: number
}

export interface CategoryPeriodComparison {
  category: string
  current_total: number
  previous_total: number
}

export interface CategoryTrendPoint {
  date: string
  category: string
  total: number
}

export interface QaAnswer {
  answer: string
  sql: string | null
}

export interface QaExchange {
  question: string
  answer: string | null
  sql: string | null
  error: string | null
}

export interface Filters {
  category: string | null
  dateFrom: string
  dateTo: string
  includeTransfers: boolean
}

export type SortColumn = 'date' | 'merchant' | 'category' | 'amount' | 'payment_method' | 'is_transfer'
export type SortDir = 'asc' | 'desc'

export interface TransactionQuery {
  dateFrom: string
  dateTo: string
  category: string | null
  includeTransfers: boolean
  sortBy: SortColumn
  sortDir: SortDir
  page: number
  pageSize: number
}

export interface TransactionPage {
  items: Transaction[]
  total: number
}
