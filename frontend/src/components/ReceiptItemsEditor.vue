<script setup lang="ts">
import type { TransactionItemInput } from '../types'

const props = defineProps<{ items: TransactionItemInput[] }>()

const emit = defineEmits<{
  'update:items': [TransactionItemInput[]]
}>()

function patch(index: number, changes: Partial<TransactionItemInput>) {
  emit(
    'update:items',
    props.items.map((item, i) => (i === index ? { ...item, ...changes } : item)),
  )
}

function remove(index: number) {
  emit('update:items', props.items.filter((_, i) => i !== index))
}
</script>

<template>
  <table class="items-editor">
    <thead>
      <tr>
        <th>Item</th>
        <th class="num">Qty</th>
        <th class="num">Subtotal</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(item, i) in items" :key="i">
        <td>
          <input type="text" :value="item.name" @input="patch(i, { name: ($event.target as HTMLInputElement).value })" />
        </td>
        <td class="num">
          <input
            type="number"
            min="0"
            step="1"
            :value="item.quantity"
            @input="patch(i, { quantity: Number(($event.target as HTMLInputElement).value) })"
          />
        </td>
        <td class="num">
          <input
            type="number"
            min="0"
            step="0.01"
            :value="item.subtotal"
            @input="patch(i, { subtotal: Number(($event.target as HTMLInputElement).value) })"
          />
        </td>
        <td class="remove-col">
          <button type="button" class="remove-btn" title="Remove item" @click="remove(i)">✕</button>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.items-editor {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.items-editor th {
  text-align: left;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-secondary);
  padding: 0.3rem 0.4rem;
}

.items-editor th.num {
  text-align: right;
}

.items-editor td {
  padding: 0.25rem 0.4rem;
  border-bottom: 1px solid var(--border);
}

.items-editor td.num {
  text-align: right;
}

.items-editor input {
  width: 100%;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 0.85rem;
  padding: 0.2rem 0;
}

.items-editor td.num input {
  text-align: right;
}

.items-editor input:focus {
  outline: none;
  border-bottom: 1px solid var(--accent);
}

.remove-col {
  width: 1%;
}

.remove-btn {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.8rem;
  padding: 0.2rem 0.3rem;
}

.remove-btn:hover {
  color: var(--danger);
}
</style>
