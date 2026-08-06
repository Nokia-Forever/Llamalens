<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string; label?: string }>()
const kind = computed(() => {
  if (['succeeded', 'running', 'active', 'healthy'].includes(props.status)) return 'success'
  if (['failed', 'error', 'inactive', 'cancelled'].includes(props.status)) return 'danger'
  if (['queued', 'activating', 'warming_up'].includes(props.status)) return 'warning'
  return 'neutral'
})
</script>

<template>
  <span class="status-badge" :class="`status-${kind}`">{{ label || status }}</span>
</template>
