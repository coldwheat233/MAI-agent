export interface ElectronAPI {
  platform: string
  version: string
  selectFolder: () => Promise<string | null>
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}
