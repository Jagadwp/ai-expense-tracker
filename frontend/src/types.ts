export interface Transaction {
  date: string | null
  merchant: string | null
  category: string | null
  amount: number | null
  payment_method: string | null
  is_transfer: boolean
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

export interface Filters {
  category: string | null
  dateFrom: string
  dateTo: string
  sortBy: 'date' | 'amount'
  includeTransfers: boolean
}
