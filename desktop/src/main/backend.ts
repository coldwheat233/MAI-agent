/**
 * Python Backend Process Manager
 */
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import http from 'http'
import { app } from 'electron'

const SERVER_PORT = parseInt(process.env.MAI_PORT || '8765')
const SERVER_URL = `http://localhost:${SERVER_PORT}`
const PYTHON_CMD = 'python'
const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..')

let pythonProcess: ChildProcess | null = null
let stopping = false

/** 返回后端启动命令。打包模式 spawn 自包含 backend.exe，开发模式 spawn 系统 Python。 */
function backendCommand(): { cmd: string; args: string[]; cwd: string } {
  if (app.isPackaged) {
    // 打包模式：backend.exe 经 extraResources 打到 resources/backend/backend.exe，
    // 自包含 Python，无系统依赖、无黑框，端口经 MAI_PORT 环境变量传入。
    const exePath = path.join(process.resourcesPath, 'backend', 'backend.exe')
    return { cmd: exePath, args: [], cwd: path.dirname(exePath) }
  }
  // 开发模式：复用项目里的 Python + mai_agent 包
  return {
    cmd: PYTHON_CMD,
    args: [
      '-X', 'utf8',
      '-c',
      `import uvicorn; from mai_agent.server import app; uvicorn.run(app, host="127.0.0.1", port=${SERVER_PORT}, log_level="error")`,
    ],
    cwd: PROJECT_ROOT,
  }
}

export function startPythonBackend(): Promise<void> {
  return new Promise((resolve, reject) => {
    stopping = false
    // Check if port already in use (previous session may still be running)
    http.get(`${SERVER_URL}/api/tools`, (res) => {
      if (res.statusCode === 200) {
        console.log('[electron] Backend already running, reusing')
        resolve()
        return
      }
      doSpawn()
    }).on('error', () => {
      doSpawn()
    })

    function doSpawn() {
      const env = {
        ...process.env,
        MAI_PORT: String(SERVER_PORT),
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
      }

      const { cmd, args, cwd } = backendCommand()
      pythonProcess = spawn(cmd, args, {
        cwd,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      })

      pythonProcess.stdout?.on('data', (data: Buffer) => {
        const msg = data.toString('utf8').trim()
        if (msg) console.log('[python]', msg)
      })

      pythonProcess.stderr?.on('data', (data: Buffer) => {
        const msg = data.toString('utf8').trim()
        if (msg && !msg.includes('Application startup complete')) {
          console.log('[python:stderr]', msg)
        }
      })

      pythonProcess.on('error', (err: Error) => {
        reject(new Error(`Cannot start Python backend: ${err.message}`))
      })

      pythonProcess.on('exit', (code: number | null) => {
        // 主动退出（stopPythonBackend 已置 stopping）时不再重启，避免孤儿进程
        if (stopping) return
        if (code !== 0) {
          console.log(`[python] Process exited (code=${code}), retrying...`)
          setTimeout(() => startPythonBackend().catch(() => {}), 2000)
        }
      })

      // Poll until server is ready
      let attempts = 0
      const maxAttempts = 30
      const check = () => {
        attempts++
        http.get(`${SERVER_URL}/api/tools`, (res) => {
          if (res.statusCode === 200) {
            console.log('[python] Backend ready')
            resolve()
          } else if (attempts < maxAttempts) {
            setTimeout(check, 500)
          } else {
            reject(new Error('Backend startup timeout'))
          }
        }).on('error', () => {
          if (attempts < maxAttempts) {
            setTimeout(check, 500)
          } else {
            reject(new Error('Backend startup timeout'))
          }
        })
      }
      setTimeout(check, 1000)
    }
  })
}

export function stopPythonBackend() {
  stopping = true
  const proc = pythonProcess
  pythonProcess = null
  if (proc) {
    proc.kill('SIGTERM')
    // 兜底 SIGKILL：捕获局部引用，之前的 bug 是先置 pythonProcess=null 再判断 → 永不触发
    setTimeout(() => {
      if (!proc.killed) {
        proc.kill('SIGKILL')
      }
    }, 3000)
  }
}
