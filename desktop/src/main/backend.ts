/**
 * Python Backend Process Manager
 */
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import http from 'http'

const SERVER_PORT = parseInt(process.env.MAI_PORT || '8765')
const SERVER_URL = `http://localhost:${SERVER_PORT}`
const PYTHON_CMD = 'python'
const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..')

let pythonProcess: ChildProcess | null = null

export function startPythonBackend(): Promise<void> {
  return new Promise((resolve, reject) => {
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
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
      }

      pythonProcess = spawn(PYTHON_CMD, [
        '-X', 'utf8',
        '-c',
        `import uvicorn; from mai_agent.server import app; uvicorn.run(app, host="127.0.0.1", port=${SERVER_PORT}, log_level="error")`
      ], {
        cwd: PROJECT_ROOT,
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
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM')
    setTimeout(() => {
      if (pythonProcess && !pythonProcess.killed) {
        pythonProcess.kill('SIGKILL')
      }
    }, 3000)
    pythonProcess = null
  }
}
