export interface ElectronAPI {
  platform: string
  version: string
  selectFolder: () => Promise<string | null>
  getPathForFile: (file: File) => string
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}
