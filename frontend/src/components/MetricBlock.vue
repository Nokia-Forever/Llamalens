<script setup lang="ts">
defineProps<{ label: string; value: string; detail?: string; accent?: boolean }>()
</script>

<template>
  <div class="metric-block" :class="{ 'metric-accent': accent }">
    <span>{{ label }}</span>
    <strong>{{ value }}</strong>
    <small v-if="detail">{{ detail }}</small>
  </div>
</template>
