import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [svelte()],
  base: '/',
  build: {
    outDir: resolve(import.meta.dirname, '../../usr/share/mcp-appliance/web'),
    emptyOutDir: true,
    assetsDir: 'assets'
  }
});
