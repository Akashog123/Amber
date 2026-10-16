// IndexedDB-backed document storage utilities
// Documents (PDF, DOC, DOCX, TXT) are stored locally so they survive page reloads

const DB_NAME = "amber-documents"
const STORE_NAME = "files"

export const openDocumentDatabase = () =>
  new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME)
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })

export const storeDocument = async (file: File): Promise<string> => {
  const id = `document-${Date.now()}-${crypto.randomUUID()}`
  const database = await openDocumentDatabase()
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite")
    transaction.objectStore(STORE_NAME).put(file, id)
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
  })
  database.close()
  return id
}

export const getStoredDocument = async (
  fileId: string,
): Promise<File | undefined> => {
  const database = await openDocumentDatabase()
  const file = await new Promise<File | undefined>((resolve, reject) => {
    const request = database
      .transaction(STORE_NAME, "readonly")
      .objectStore(STORE_NAME)
      .get(fileId)
    request.onsuccess = () => resolve(request.result as File | undefined)
    request.onerror = () => reject(request.error)
  })
  database.close()
  return file
}

export const openStoredDocument = async (fileId: string): Promise<void> => {
  const preview = window.open("about:blank", "_blank")
  if (preview) {
    preview.opener = null
    preview.document.title = "Opening document…"
    preview.document.body.textContent = "Opening your Amber document…"
  }
  const file = await getStoredDocument(fileId)
  if (!file) {
    preview?.close()
    throw new Error("Document not found")
  }
  const url = URL.createObjectURL(file)
  if (preview) preview.location.href = url
  else window.open(url, "_blank", "noopener,noreferrer")
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
