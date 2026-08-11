/**
 * MAI-agent Desktop — Preload Script
 * Secure bridge between renderer and main process.
 * contextIsolation: true → web pages cannot access Node.js APIs directly.
 */
import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  version: process.versions.electron,
  selectFolder: () => ipcRenderer.invoke('select-folder'),
})
