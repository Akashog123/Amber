import { useEffect, useState } from "react"
import { ExternalLink, FileCheck2, X } from "lucide-react"
import { formatFileSize } from "../types"
import { getStoredDocument, openStoredDocument } from "../documentUtils"

function PdfPreview({
  fileId,
  name,
  onRemove,
}: {
  fileId?: string
  name: string
  onRemove: () => void
}) {
  const [url, setUrl] = useState("")
  const [unavailable, setUnavailable] = useState(false)
  const isPdf = name.toLowerCase().endsWith(".pdf")

  useEffect(() => {
    if (!fileId || !isPdf) return
    let objectUrl = ""
    let active = true
    void getStoredDocument(fileId)
      .then((file) => {
        if (!active || !file) {
          if (active) setUnavailable(true)
          return
        }
        objectUrl = URL.createObjectURL(file)
        setUrl(objectUrl)
        setUnavailable(false)
      })
      .catch(() => {
        if (active) setUnavailable(true)
      })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [fileId, isPdf])

  if (!isPdf) return null
  if (unavailable)
    return (
      <p className="rounded-xl bg-[#fff5f5] px-4 py-3 text-center text-xs font-semibold text-[#bd4545]">
        Preview unavailable. Re-upload the PDF to view it here.
      </p>
    )
  if (!url)
    return (
      <div className="grid h-full place-items-center bg-[#f1f4f8] text-sm font-semibold text-[#74819a]">
        Preparing PDF previewâ€¦
      </div>
    )

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#eef2f7]">
      <div className="flex items-center gap-3 border-b border-[#d8e1ee] bg-white px-3 py-2">
        <span className="min-w-0 flex-1 truncate text-left text-sm font-bold text-[#526079]">
          {name}
        </span>
        <button
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[#bfd1eb] px-3 py-1.5 text-xs font-bold text-[#3479f5] hover:border-[#3479f5]"
          type="button"
          onClick={() => fileId && void openStoredDocument(fileId)}
        >
          <ExternalLink className="h-3.5 w-3.5" /> Open
        </button>
        <button
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#7b879c] hover:bg-[#fff0f0] hover:text-[#c94848]"
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${name}`}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <object
        className="min-h-0 w-full flex-1 bg-white"
        data={url}
        type="application/pdf"
        aria-label={`Preview of ${name}`}
      >
        <div className="grid h-72 place-items-center px-6 text-center">
          <div>
            <p className="text-sm font-semibold text-[#526079]">
              Your browser cannot display this PDF inline.
            </p>
            <button
              className="mt-3 rounded-full bg-[#3479f5] px-5 py-2.5 text-sm font-bold text-white"
              type="button"
              onClick={() => fileId && void openStoredDocument(fileId)}
            >
              Open PDF
            </button>
          </div>
        </div>
      </object>
    </div>
  )
}

function UploadedDocument({
  name,
  fileId,
  size,
  type,
  onRemove,
}: {
  name: string
  fileId?: string
  size?: number
  type?: string
  onRemove?: () => void
}) {
  const [message, setMessage] = useState("")
  const openFile = async () => {
    if (!fileId) {
      setMessage("Re-upload this document to open it.")
      return
    }
    try {
      await openStoredDocument(fileId)
      setMessage("")
    } catch {
      setMessage("This document is no longer available. Please re-upload it.")
    }
  }

  return (
    <div>
      <div className="flex items-center gap-3 rounded-xl border border-[#cfe0f6] bg-[#f5f9ff] p-3 text-left">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-[#3479f5] shadow-sm">
          <FileCheck2 className="h-5 w-5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-bold text-[#263653]">
            {name}
          </span>
          <span className="mt-0.5 block text-xs text-[#74819a]">
            {[
              type?.split("/").pop()?.toUpperCase(),
              formatFileSize(size),
              "Uploaded",
            ]
              .filter(Boolean)
              .join(" Â· ")}
          </span>
        </span>
        <button
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[#bfd1eb] bg-white px-3 py-2 text-xs font-bold text-[#3479f5] hover:border-[#3479f5]"
          type="button"
          onClick={openFile}
        >
          <ExternalLink className="h-3.5 w-3.5" /> Open
        </button>
        {onRemove && (
          <button
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#7b879c] hover:bg-white hover:text-[#c94848]"
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${name}`}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      {message && (
        <p className="mt-2 text-xs font-semibold text-[#c94848]" role="status">
          {message}
        </p>
      )}
    </div>
  )
}
