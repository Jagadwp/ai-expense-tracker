<script setup lang="ts">
import { computed, ref } from 'vue'
import { createTransaction, updateTransaction } from '../api'
import type { ReceiptScanResult, Transaction, TransactionInput, TransactionItemInput } from '../types'
import ReceiptItemsEditor from './ReceiptItemsEditor.vue'
import ReceiptScanner from './ReceiptScanner.vue'

// Fixed sets, not "whatever's already in the data" — category mirrors the
// LLM extraction schema's enum (app/extraction.py's Category literal), and
// payment method is a curated list of common Indonesian payment methods,
// so manual entries and (once app/extraction.py is updated to match) LLM
// extractions stay in the same fixed vocabulary instead of free text.
const CATEGORIES = ['food', 'transport', 'shopping', 'bills', 'entertainment', 'other']
const PAYMENT_METHODS = [
  'Cash',
  'QRIS',
  'Debit Card',
  'Credit Card',
  'Bank Transfer',
  'Virtual Account',
  'GoPay',
  'OVO',
  'Dana',
  'ShopeePay',
  'LinkAja',
]

const props = defineProps<{
  editing?: Transaction | null
}>()

// A pre-existing (e.g. LLM-extracted, pre-enum) value outside the fixed
// list would otherwise vanish from view in a <select> — keep it selectable
// so opening "Edit" never silently changes data the user didn't touch.
const categoryOptions = computed(() =>
  props.editing?.category && !CATEGORIES.includes(props.editing.category)
    ? [props.editing.category, ...CATEGORIES]
    : CATEGORIES,
)
const paymentMethodOptions = computed(() =>
  props.editing?.payment_method && !PAYMENT_METHODS.includes(props.editing.payment_method)
    ? [props.editing.payment_method, ...PAYMENT_METHODS]
    : PAYMENT_METHODS,
)

const emit = defineEmits<{
  saved: []
  close: []
}>()

// "Today" always means Indonesia (WIB), not the browser's own timezone —
// consistent with the backend (app/main.py's JAKARTA_TZ).
function todayJakarta(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Jakarta' })
}

function toInput(detail: Transaction | null | undefined): TransactionInput {
  return {
    date: detail?.date?.slice(0, 10) ?? todayJakarta(),
    merchant: detail?.merchant ?? '',
    amount: detail?.amount ?? null,
    currency: 'IDR',
    category: detail?.category ?? null,
    payment_method: detail?.payment_method ?? null,
    is_transfer: detail?.is_transfer ?? false,
  }
}

const form = ref<TransactionInput>(toInput(props.editing))
const saving = ref(false)
const error = ref<string | null>(null)

// Only offered for brand-new transactions — editing an existing one already
// has its own line items via TransactionPreviewModal's ReceiptScanner.
const scannedItems = ref<TransactionItemInput[] | null>(null)

// Pre-fills empty fields only — never silently overwrite something the user
// already typed themselves.
function onScanned(result: ReceiptScanResult) {
  if (!form.value.merchant && result.merchant) form.value.merchant = result.merchant
  if (!form.value.date && result.date) form.value.date = result.date
  if (form.value.amount === null && result.total !== null) form.value.amount = result.total
  scannedItems.value = result.items.length ? result.items : null
}

async function save() {
  saving.value = true
  error.value = null
  try {
    const payload: TransactionInput = {
      ...form.value,
      date: form.value.date || null,
      merchant: form.value.merchant || null,
      ...(scannedItems.value ? { items: scannedItems.value } : {}),
    }
    if (props.editing) {
      await updateTransaction(props.editing.message_id, payload)
    } else {
      await createTransaction(payload)
    }
    emit('saved')
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="modal">
      <header>
        <h3>{{ editing ? 'Edit transaction' : 'Add transaction' }}</h3>
        <button class="close" @click="emit('close')">✕</button>
      </header>

      <div v-if="!editing" class="scan-section">
        <span class="scan-label">Scan receipt</span>
        <p class="scan-pitch">Skip the typing, scan your receipt and let AI do the rest.</p>
        <div class="scan-body">
          <ReceiptScanner @scanned="onScanned" />
          <template v-if="scannedItems">
            <p class="scan-hint">{{ scannedItems.length }} item(s) will be saved with this transaction — edit before saving if needed.</p>
            <ReceiptItemsEditor :items="scannedItems" @update:items="scannedItems = $event" />
          </template>
        </div>
      </div>

      <form class="fields" @submit.prevent="save">
        <label>
          <span class="label-text">Date <span class="required">*</span></span>
          <input v-model="form.date" type="date" required />
        </label>
        <label>
          <span class="label-text">Merchant</span>
          <input v-model="form.merchant" type="text" placeholder="e.g. Indomaret" />
        </label>
        <label>
          <span class="label-text">Amount <span class="required">*</span></span>
          <input v-model.number="form.amount" type="number" step="0.01" min="0" required />
        </label>
        <label>
          <span class="label-text">Category</span>
          <select v-model="form.category">
            <option :value="null">—</option>
            <option v-for="c in categoryOptions" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <label>
          <span class="label-text">Payment method</span>
          <select v-model="form.payment_method">
            <option :value="null">—</option>
            <option v-for="m in paymentMethodOptions" :key="m" :value="m">{{ m }}</option>
          </select>
        </label>
        <label class="checkbox">
          <input v-model="form.is_transfer" type="checkbox" />
          This is a fund transfer, not spending
        </label>

        <p v-if="error" class="error">{{ error }}</p>

        <div class="actions">
          <button type="button" class="cancel" @click="emit('close')">Cancel</button>
          <button type="submit" class="save" :disabled="saving">{{ saving ? 'Saving…' : 'Save' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(17, 24, 39, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  z-index: 100;
}

.modal {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  width: 100%;
  max-width: 600px; 
  padding: 1.5rem;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

header h3 {
  font-size: 1.1rem;
}

.close {
  border: none;
  background: transparent;
  font-size: 1rem;
  color: var(--text-secondary);
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
}

.close:hover {
  background: var(--bg);
}

.scan-section {
  margin-bottom: 1rem;
  border: 1px solid var(--border);
  background: var(--bg);
  border-radius: 8px;
  padding: 0.75rem;
}

.scan-label {
  display: block;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary);
}

.scan-pitch {
  margin: 0.25rem 0 0;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.scan-body {
  margin-top: 0.75rem;
  max-height: 380px;
  overflow-y: auto;
}

.scan-hint {
  color: var(--text-secondary);
  font-size: 0.8rem;
  margin: 0.5rem 0 0;
}

.fields {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

label.checkbox {
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
}

input[type='text'],
input[type='date'],
input[type='number'],
select {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-primary);
  border-radius: 6px;
  padding: 0.45rem 0.6rem;
  font-size: 0.85rem;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
  margin-top: 0.5rem;
}

.cancel {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-primary);
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
}

.save {
  border: none;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
}

.save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  color: var(--danger);
  font-size: 0.8rem;
  margin: 0;
}

.required {
  color: var(--danger);
}

@media (max-width: 600px) {
  .overlay {
    padding: 0.75rem;
    align-items: flex-end;
  }

  .modal {
    padding: 1rem;
    max-height: 90vh;
    overflow-y: auto;
  }
}
</style>
