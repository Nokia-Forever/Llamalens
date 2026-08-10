<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <section class="chart-card">
    <div class="chart-card-heading">
      <div>
        <h3>{{ title }}</h3>
        <p v-if="description">{{ description }}</p>
      </div>
      <div class="chart-card-actions"><slot name="actions" /></div>
    </div>
    <div class="chart-card-body"><slot /></div>
  </section>
</template>
