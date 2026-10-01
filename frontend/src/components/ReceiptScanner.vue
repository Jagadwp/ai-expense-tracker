<script setup lang="ts">
import { ref } from 'vue'
import { scanReceipt } from '../api'
import type { ReceiptScanResult } from '../types'

const emit = defineEmits<{
  scanned: [ReceiptScanResult]
}>()

const file = ref<File | null>(null)
const previewUrl = ref<string | null>(null)
// True when <img> can't decode the file (e.g. HEIC) — hide the thumbnail instead of a broken-image icon.
const previewFailed = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0] ?? null
  file.value = picked
  error.value = null
  previewFailed.value = false

  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = null
  }
  if (picked) {
    previewUrl.value = URL.createObjectURL(picked)
  }
}

async function scan() {
  if (!file.value) return
  saving.value = true
  error.value = null
  try {
    const result = await scanReceipt(file.value)
    const isEmpty = !result.merchant && !result.date && result.total === null && result.items.length === 0
    if (isEmpty) {
      error.value = "Couldn't find any receipt details in that image — try a clearer photo of a receipt."
      return
    }
    emit('scanned', result)
  } catch (err) {
    // Surface a plain, non-technical message — the raw error (HTTP status,
    // stack) is still logged for debugging, just not shown to the user.
    console.error('Receipt scan failed:', err)
    error.value = "Couldn't read that receipt — try a clearer photo or a different file."
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="receipt-scanner">
    <input type="file" accept="image/*" capture="environment" @change="onFileChange" />
    <img
      v-if="previewUrl && !previewFailed"
      :src="previewUrl"
      alt="Receipt preview"
      class="thumbnail"
      @error="previewFailed = true"
    />
    <button type="button" class="scan-btn" :disabled="!file || saving" @click="scan">
      {{ saving ? 'Scanning…' : 'Scan receipt' }}
    </button>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

<style scoped>
.receipt-scanner {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

input[type='file'] {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.thumbnail {
  max-width: 180px;
  max-height: 180px;
  border: 1px solid var(--border);
  border-radius: 8px;
  object-fit: contain;
}

.scan-btn {
  align-self: flex-start;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-primary);
  border-radius: 8px;
  padding: 0.45rem 0.9rem;
  font-size: 0.85rem;
}

.scan-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.scan-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  color: var(--danger);
  font-size: 0.8rem;
  margin: 0;
}

@media (max-width: 600px) {
  .thumbnail {
    max-width: 140px;
    max-height: 140px;
  }
}
</style>
