/**
 * System Tray Icon
 */
import { Tray, Menu, app, nativeImage } from 'electron'
import path from 'path'
import fs from 'fs'
import { getMainWindow } from './window'
import { makeBrandIcon } from './icon'

let tray: Tray | null = null

export function createTray() {
  try {
    const trayIconPath = path.join(__dirname, '..', '..', 'assets', 'tray-icon.png')
    // Fallback: 程序化生成品牌图标（与任务栏一致），文件存在则优先用文件
    let icon: Electron.NativeImage
    if (fs.existsSync(trayIconPath)) {
      icon = nativeImage.createFromPath(trayIconPath)
    } else {
      icon = makeBrandIcon(16, true)
    }

    tray = new Tray(icon.resize({ width: 16, height: 16 }))

    const contextMenu = Menu.buildFromTemplate([
      {
        label: 'Show Window',
        click: () => {
          const win = getMainWindow()
          if (win) win.show()
        },
      },
      { type: 'separator' },
      {
        label: 'Quit',
        click: () => {
          globalThis.__isQuitting = true
          app.quit()
        },
      },
    ])

    tray.setToolTip('MAI-agent Desktop')
    tray.setContextMenu(contextMenu)
    tray.on('double-click', () => {
      const win = getMainWindow()
      if (win) win.show()
    })
  } catch (e) {
    // Tray icon is non-critical
  }
}
