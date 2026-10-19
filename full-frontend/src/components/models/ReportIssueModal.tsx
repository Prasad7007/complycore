import * as React from "react"
import { createPortal } from "react-dom"
import { X, Upload, CheckCircle2, AlertCircle } from "lucide-react"
import { API_BASE_URL } from "@/lib/api"

export type ReportIssueModalProps = {
  onClose: () => void
  currentUserInfo: any
}

const focusStyles = "focus:border-[#128BDA] focus:outline-none focus:ring-1 focus:ring-[#128BDA]/30"

export function ReportIssueModal({ onClose, currentUserInfo }: ReportIssueModalProps) {
  const [description, setDescription] = React.useState("")
  const [file, setFile] = React.useState<File | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [success, setSuccess] = React.useState(false)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0])
    } else {
      setFile(null)
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!description.trim()) {
      setError("Please provide a description of the issue.")
      return
    }

    setBusy(true)
    setError(null)

    const formData = new FormData()
    formData.append("description", description)
    if (file) {
      formData.append("file", file)
    }

    try {
      const response = await fetch(`${API_BASE_URL}/users/report-issue`, {
        method: "POST",
        credentials: "include",
        body: formData,
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({ detail: "Failed to submit report." }))
        throw new Error(errData.detail || "Failed to submit report.")
      }

      setSuccess(true)
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred.")
    } finally {
      setBusy(false)
    }
  }

  if (typeof document === "undefined") return null

  const userName = currentUserInfo?.full_name || currentUserInfo?.email || "User"
  const orgName = currentUserInfo?.organization?.name || "No Organization"
  const currentTime = new Date().toLocaleString()

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-md px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Report an Issue"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="flex w-[500px] max-w-full flex-col rounded-2xl border border-border bg-card p-6 shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:bg-gradient-to-br dark:from-[#1e3a5f] dark:to-[#312e81] dark:backdrop-blur-[20px] dark:shadow-[0_0_50px_rgba(30,58,95,0.4),0_25px_50px_-12px_rgba(0,0,0,0.5)]"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h2
              className="text-lg font-semibold text-foreground"
              style={{ fontFamily: "Inter, sans-serif" }}
            >
              Report an Issue
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Please describe the issue. Our support team will investigate.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-5 w-5" strokeWidth={2} />
          </button>
        </div>

        {success ? (
          <div className="mt-8 flex flex-col items-center text-center py-6">
            <CheckCircle2 className="h-12 w-12 text-emerald-500 mb-3" />
            <h3 className="text-base font-semibold text-foreground">Issue Submitted</h3>
            <p className="mt-2 text-sm text-muted-foreground max-w-xs">
              Thank you for reporting this issue. We have sent the report to <strong>info@complycore.ca</strong>.
            </p>
            <button
              type="button"
              onClick={onClose}
              className="mt-6 h-10 px-6 rounded-lg bg-[#174199] text-sm font-semibold text-white hover:bg-[#174199]/90 transition-colors"
            >
              Close
            </button>
          </div>
        ) : (
          <form className="mt-6 flex flex-col gap-4" onSubmit={handleSubmit}>
            {error && (
              <div className="flex items-start gap-2 rounded-lg bg-red-500/10 p-3 border border-red-500/20 text-xs text-red-600 dark:text-red-400">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {/* Auto-captured metadata info box */}
            <div className="rounded-lg bg-muted/50 border border-border/60 p-3 text-xs text-muted-foreground space-y-1">
              <div className="flex justify-between">
                <span>Reporter:</span>
                <span className="font-medium text-foreground">{userName}</span>
              </div>
              <div className="flex justify-between">
                <span>Organization:</span>
                <span className="font-medium text-foreground">{orgName}</span>
              </div>
              {/* <div className="flex justify-between">
                <span>Timestamp:</span>
                <span className="font-medium text-foreground">{currentTime}</span>
              </div> */}
            </div>

            {/* Description Field */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-foreground">
                Description of the Issue
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe what happened, what you expected, and steps to reproduce the issue."
                className={`w-full min-h-[120px] rounded-lg border border-input bg-background p-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-[#128BDA]/30 resize-y ${focusStyles}`}
                disabled={busy}
                required
              />
            </div>

            {/* File Upload Field */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-foreground">
                Attach Screenshot or Supporting File
              </label>
              <div className="relative flex items-center justify-center border border-dashed border-input rounded-lg hover:bg-muted/35 transition-colors p-4">
                <input
                  type="file"
                  id="issue-file-upload"
                  onChange={handleFileChange}
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  disabled={busy}
                />
                <div className="flex flex-col items-center gap-1.5 text-center text-xs text-muted-foreground pointer-events-none">
                  <Upload className="h-5 w-5 text-muted-foreground/80" />
                  {file ? (
                    <span className="font-medium text-foreground truncate max-w-[250px]">
                      {file.name} ({(file.size / 1024).toFixed(1)} KB)
                    </span>
                  ) : (
                    <span>Click or drag to upload a file</span>
                  )}
                </div>
              </div>
            </div>

            {/* Submit Actions */}
            <div className="mt-4 flex gap-3">
              <button
                type="button"
                onClick={onClose}
                disabled={busy}
                className="h-10 flex-1 rounded-lg border border-input bg-background text-sm font-semibold text-foreground hover:bg-accent disabled:opacity-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy}
                className="h-10 flex-1 rounded-lg bg-[#174199] text-sm font-semibold text-white hover:bg-[#174199]/90 disabled:opacity-50 transition-colors shadow-sm"
              >
                {busy ? "Submitting..." : "Submit Report"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body
  )
}
