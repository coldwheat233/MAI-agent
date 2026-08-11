/**
 * MAI-agent Desktop — Electron Main Process
 * Architecture: Electron (Chromium) → localhost:8765 (FastAPI + WebSocket)
 */
import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { startPythonBackend, stopPythonBackend } from './backend'
import { createWindow, getMainWindow } from './window'
import { createTray } from './tray'
import { createMenu } from './menu'

let isQuitting = false

// IPC: folder picker for workspace setting
ipcMain.handle('select-folder', async () => {
  const win = getMainWindow()
  if (!win) return null
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory'],
    title: 'Select Workspace Folder',
  })
  return result.canceled ? null : result.filePaths[0]
})

app.whenReady().then(async () => {
  try {
    console.log('[electron] Starting Python backend...')
    await startPythonBackend()
    await createWindow()
    createTray()
  } catch (err: any) {
    dialog.showErrorBox(
      'Startup Failed',
      `Cannot start MAI-agent backend:\n${err.message}\n\nPlease ensure Python is correctly configured.`
    )
    app.quit()
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    isQuitting = true
    app.quit()
  }
})

app.on('activate', () => {
  const win = getMainWindow()
  if (win === null) {
    createWindow()
  } else {
    win.show()
  }
})

app.on('before-quit', () => {
  isQuitting = true
  stopPythonBackend()
})

// Prevent multiple instances
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isMinimized()) win.restore()
      win.show()
      win.focus()
    }
  })
}
