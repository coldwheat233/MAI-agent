/**
 * MAI-agent Desktop — Preload Script
 * Secure bridge between renderer and main process.
 * contextIsolation: true → web pages cannot access Node.js APIs directly.
 */
import { contextBridge, ipcRenderer, webUtils } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  version: process.versions.electron,
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  // Electron 32+ 移除了 File.path，拖拽文件夹必须用 webUtils.getPathForFile。
  getPathForFile: (file: File) => webUtils.getPathForFile(file),
})
