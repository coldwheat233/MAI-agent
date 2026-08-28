/**
 * System Tray Icon
 */
import { Tray, Menu, app, nativeImage } from 'electron'
import path from 'path'
import fs from 'fs'
import { getMainWindow } from './window'

let tray: Tray | null = null

/**
 * 程序化生成托盘图标（16x16 SVG → PNG dataURL）。
 *
 * 不依赖外部图片文件（assets/tray-icon.png 可能缺失 → 之前是空图标）。
 * 设计: 圆角方块 + 居中"M"字母。跟随系统主题自动切深/浅色，
 * Windows 托盘在浅色任务栏上要深色图标、深色任务栏要浅色图标。
 */
function makeTrayIcon(): Electron.NativeImage {
  // 按平台选配色：macOS 菜单栏深色→浅色图标；Windows 任务栏浅色→深色图标
  const isMac = process.platform === 'darwin'
  const fg = isMac ? '#FFFFFF' : '#1F2937' // 前景（M 字母）
  const bg = isMac ? '#6366F1' : '#4F46E5' // 背景（indigo 品牌色）

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <rect x="1" y="1" width="14" height="14" rx="3.5" fill="${bg}"/>
  <text x="8" y="11.5" font-family="Arial, sans-serif" font-size="9.5" font-weight="bold"
        text-anchor="middle" fill="${fg}">M</text>
</svg>`

  const dataUrl = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
  const icon = nativeImage.createFromDataURL(dataUrl)
  return icon.resize({ width: 16, height: 16 })
}

export function createTray() {
  try {
    const trayIconPath = path.join(__dirname, '..', '..', 'assets', 'tray-icon.png')
    // Fallback: create a small 16x16 icon programmatically if file doesn't exist
    let icon: Electron.NativeImage
    if (fs.existsSync(trayIconPath)) {
      icon = nativeImage.createFromPath(trayIconPath)
    } else {
      icon = makeTrayIcon()
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
