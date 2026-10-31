import { Fragment } from 'react'

const KW_PY = /\b(def|return|import|from|with|as|if|and|or|not|raise|class|None|True|False|in|is|for|while|try|except|else|elif|lambda)\b/
const KW_SQL = /\b(CREATE|TABLE|IF|NOT|EXISTS|NULL|DEFAULT|PRIMARY|KEY|ALTER|ADD|CONSTRAINT|UNIQUE|DELETE|FROM|USING|WHERE|AND|INSERT|INTO|VALUES|ON|CONFLICT|DO|NOTHING|UPDATE|SET|SELECT)\b/i

/** Tiny dependency-free highlighter; good enough for py/sql diffs. */
export function highlight(text: string, lang: string): React.ReactNode {
  const sql = /\.sql$/.test(lang)
  const kw = sql ? KW_SQL : KW_PY
  const re = new RegExp(
    `(${sql ? '--.*$' : '#.*$'})|("(?:[^"\\\\]|\\\\.)*"|'(?:[^'\\\\]|\\\\.)*')|(\\b\\d+(?:\\.\\d+)?\\b)|(${kw.source})`,
    sql ? 'gi' : 'g',
  )
  const out: React.ReactNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const cls = m[1] ? 'tk-c' : m[2] ? 'tk-s' : m[3] ? 'tk-n' : 'tk-k'
    out.push(<span key={i++} className={cls}>{m[0]}</span>)
    last = m.index + m[0].length
    if (m[0].length === 0) re.lastIndex++
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function Code({ lines, start, lang }: { lines: string[]; start: number; lang: string }) {
  return (
    <div className="code" role="region" aria-label="Source excerpt" tabIndex={0}>
      {lines.map((l, i) => (
        <div className="code-line" key={i}>
          <span className="ln">{start + i}</span>
          <span className="lt">{highlight(l, lang) || ' '}</span>
        </div>
      ))}
    </div>
  )
}

interface DiffLine { t: 'add' | 'del' | 'ctx' | 'hunk'; text: string; o?: number; n?: number }
interface DiffFile { path: string; isNew: boolean; lines: DiffLine[]; add: number; del: number }

export function parseDiff(diff: string): DiffFile[] {
  const files: DiffFile[] = []
  let cur: DiffFile | null = null
  let o = 0, n = 0
  for (const raw of diff.split('\n')) {
    if (raw.startsWith('diff --git')) {
      const m = / b\/(.+)$/.exec(raw)
      cur = { path: m ? m[1] : raw, isNew: false, lines: [], add: 0, del: 0 }
      files.push(cur)
    } else if (!cur) continue
    else if (raw.startsWith('new file')) cur.isNew = true
    else if (raw.startsWith('--- ') || raw.startsWith('+++ ') || raw.startsWith('index ')) continue
    else if (raw.startsWith('@@')) {
      const m = /@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(raw)
      o = m ? +m[1] : 0
      n = m ? +m[2] : 0
      cur.lines.push({ t: 'hunk', text: raw })
    } else if (raw.startsWith('+')) { cur.lines.push({ t: 'add', text: raw.slice(1), n: n++ }); cur.add++ }
    else if (raw.startsWith('-')) { cur.lines.push({ t: 'del', text: raw.slice(1), o: o++ }); cur.del++ }
    else if (raw.startsWith(' ')) cur.lines.push({ t: 'ctx', text: raw.slice(1), o: o++, n: n++ })
  }
  return files
}

export function DiffView({ diff }: { diff: string }) {
  const files = parseDiff(diff)
  if (!files.length) return <pre className="pre">{diff}</pre>
  return (
    <div className="diff">
      {files.map((f) => (
        <Fragment key={f.path}>
          <div className="diff-file">
            <header className="diff-head">
              <span className="mono">{f.path}</span>
              {f.isNew && <span className="pill pill-new">new file</span>}
              <span className="diff-stat"><b className="plus">+{f.add}</b> <b className="minus">−{f.del}</b></span>
            </header>
            <div className="code" role="region" aria-label={`Diff of ${f.path}`} tabIndex={0}>
              {f.lines.map((l, i) =>
                l.t === 'hunk' ? (
                  <div key={i} className="code-line dl-hunk"><span className="ln" /><span className="ln" /><span className="mk" /><span className="lt">{l.text}</span></div>
                ) : (
                  <div key={i} className={`code-line dl-${l.t}`}>
                    <span className="ln">{l.o ?? ''}</span>
                    <span className="ln">{l.n ?? ''}</span>
                    <span className="mk">{l.t === 'add' ? '+' : l.t === 'del' ? '−' : ''}</span>
                    <span className="lt">{highlight(l.text, f.path) || ' '}</span>
                  </div>
                ),
              )}
            </div>
          </div>
        </Fragment>
      ))}
    </div>
  )
}
