/**
 * BrowserWindow Factory
 */
import { app, BrowserWindow, shell } from 'electron'
import path from 'path'

const SERVER_PORT = parseInt(process.env.MAI_PORT || '8765')
const SERVER_URL = `http://localhost:${SERVER_PORT}`

let mainWindow: BrowserWindow | null = null

export async function createWindow(): Promise<BrowserWindow> {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    title: 'MAI-agent Desktop',
    backgroundColor: '#0f1117',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  // Show window when ready (avoid white flash)
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })

  // Open external links in system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Dev: load from vite server (hot reload); prod: load from Python backend static files
  const isDev = !app.isPackaged && process.env.ELECTRON_RENDERER_URL
  if (isDev) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL!)
  } else {
    mainWindow.loadURL(SERVER_URL)
  }

  // Minimize to tray when closed
  mainWindow.on('close', (e) => {
    if (!globalThis.__isQuitting) {
      e.preventDefault()
      mainWindow?.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  return mainWindow
}

export function getMainWindow(): BrowserWindow | null {
  return mainWindow
}

// Expose quit flag globally for tray access
declare global {
  var __isQuitting: boolean | undefined
}
