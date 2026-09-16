import { CloudUpload, FolderOpen } from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'

import { cx } from '../../lib/cx'
import { ACCEPT_ATTRIBUTE, MAX_UPLOAD_MB } from '../../lib/uploads'
import { Button } from '../ui/Button'

interface DocumentDropzoneProps {
  onFiles: (files: File[]) => void
  disabled?: boolean
  actions?: ReactNode
}

export function DocumentDropzone({ onFiles, disabled = false, actions }: DocumentDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const dragDepth = useRef(0)
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    // A file dropped next to the zone would otherwise make the browser open it and leave the app.
    const ignoreFileDrop = (event: globalThis.DragEvent) => {
      if (event.dataTransfer?.types.includes('Files')) event.preventDefault()
    }
    window.addEventListener('dragover', ignoreFileDrop)
    window.addEventListener('drop', ignoreFileDrop)
    return () => {
      window.removeEventListener('dragover', ignoreFileDrop)
      window.removeEventListener('drop', ignoreFileDrop)
    }
  }, [])

  function handleDrag(event: DragEvent<HTMLDivElement>, delta: number) {
    event.preventDefault()
    if (disabled) return
    dragDepth.current = Math.max(0, dragDepth.current + delta)
    setDragging(dragDepth.current > 0)
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    if (disabled) return
    const files = Array.from(event.dataTransfer.files)
    if (files.length) onFiles(files)
  }

  return (
    <div
      data-testid="dropzone"
      data-dragging={dragging || undefined}
      onDragEnter={(event) => handleDrag(event, 1)}
      onDragLeave={(event) => handleDrag(event, -1)}
      onDragOver={(event) => {
        event.preventDefault()
        event.dataTransfer.dropEffect = disabled ? 'none' : 'copy'
      }}
      onDrop={handleDrop}
      className={cx(
        'rounded-xl border-2 border-dashed px-6 py-9 text-center transition-colors',
        dragging ? 'border-brand-400 bg-brand-50/80' : 'border-slate-200 bg-slate-50/60 hover:border-slate-300',
        disabled && 'opacity-60',
      )}
    >
      <div
        className={cx(
          'mx-auto grid size-12 place-items-center rounded-xl border bg-white shadow-card transition-transform',
          dragging ? 'scale-110 border-brand-200 text-brand-600' : 'border-slate-200 text-slate-500',
        )}
      >
        <CloudUpload className="size-6" />
      </div>
      <p className="mt-3 text-[15px] font-semibold text-slate-900">
        {dragging ? 'Drop to upload' : 'Drag and drop claim documents here'}
      </p>
      <p className="mt-1 text-sm text-slate-500">
        PDF, JPG or PNG · up to {MAX_UPLOAD_MB} MB each · select several files at once
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        <Button variant="secondary" onClick={() => inputRef.current?.click()} disabled={disabled}>
          <FolderOpen className="size-4" />
          Browse files
        </Button>
        {actions}
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT_ATTRIBUTE}
        disabled={disabled}
        tabIndex={-1}
        data-testid="file-input"
        aria-label="Choose documents to upload"
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? [])
          event.target.value = ''
          if (files.length) onFiles(files)
        }}
      />
    </div>
  )
}
