/**
 * 品牌图标 — 托盘 + 任务栏共用（保证一致）。
 *
 * 从 assets/ 读 PNG 文件（nativeImage 不支持 SVG dataURL，Windows 上会 empty）：
 *   - assets/tray-icon.png   16x16 托盘图标（indigo 圆角方块 + M）
 *   - assets/app-icon.png    256x256 窗口/任务栏图标（同品牌）
 * 文件缺失时降级为程序化 PNG（1x1 透明占位，避免空白异常）。
 */
import { nativeImage } from 'electron'
import path from 'path'
import fs from 'fs'

function assetPath(name: string): string {
  return path.join(__dirname, '..', '..', 'assets', name)
}

export function makeBrandIcon(size: number, forTray = false): Electron.NativeImage {
  const file = forTray ? 'tray-icon.png' : 'app-icon.png'
  const p = assetPath(file)
  if (fs.existsSync(p)) {
    const icon = nativeImage.createFromPath(p)
    if (!icon.isEmpty()) {
      return icon.resize({ width: size, height: size })
    }
  }
  // 降级：1x1 透明 PNG（保证不空白异常）
  const emptyPng =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
  return nativeImage.createFromDataURL('data:image/png;base64,' + emptyPng).resize({ width: size, height: size })
}
