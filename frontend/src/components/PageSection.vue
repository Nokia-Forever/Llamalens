<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <section class="page-section">
    <div class="section-heading">
      <h2>{{ title }}</h2>
      <p v-if="description">{{ description }}</p>
    </div>
    <div class="section-actions"><slot name="actions" /></div>
    <div class="section-body"><slot /></div>
  </section>
</template>
