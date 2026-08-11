// ── Markdown Rendering ──────────────────────────
import Markdown from 'markdown-to-jsx'
import hljs from 'highlight.js/lib/core'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import css from 'highlight.js/lib/languages/css'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import sql from 'highlight.js/lib/languages/sql'
import markdown_lang from 'highlight.js/lib/languages/markdown'
import rust from 'highlight.js/lib/languages/rust'
import java from 'highlight.js/lib/languages/java'

// Register only needed languages to keep bundle small
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('tsx', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('jsx', javascript)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('sh', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('css', css)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('yml', yaml)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('markdown', markdown_lang)
hljs.registerLanguage('md', markdown_lang)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('java', java)

export function highlightCode(code: string, lang?: string): string {
  if (lang && hljs.getLanguage(lang)) {
    try {
      return hljs.highlight(code, { language: lang }).value
    } catch {
      // fall through to auto-detect
    }
  }
  try {
    return hljs.highlightAuto(code).value
  } catch {
    return code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }
}

// Override markdown-to-jsx code block rendering
export const markdownOptions = {
  overrides: {
    pre: {
      component: (props: any) => <div {...props} />,
    },
  },
}

export { Markdown }
