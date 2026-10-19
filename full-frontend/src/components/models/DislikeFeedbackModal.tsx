import * as React from "react"
import { createPortal } from "react-dom"
import { ThumbsDown, X } from "lucide-react"

export type DislikeFeedbackModalProps = {
  open: boolean
  onClose: () => void
  onSubmit?: (feedback: string) => void
}

export function DislikeFeedbackModal({ open, onClose, onSubmit }: DislikeFeedbackModalProps) {
  const [feedback, setFeedback] = React.useState("")

  React.useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKeyDown)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  React.useEffect(() => {
    if (!open) setFeedback("")
  }, [open])

  const handleSubmit = () => {
    onSubmit?.(feedback)
    onClose()
  }

  if (!open || typeof document === "undefined") return null

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-md px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Dislike feedback"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="relative w-full max-w-[560px] rounded-xl bg-card p-6 shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <ThumbsDown className="h-5 w-5 text-red-500" />
            <h2 className="text-lg font-bold text-red-500">Dislike</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Title & Instructions */}
        <div className="mt-5">
          <h3 className="text-base font-semibold text-foreground">
            What went wrong with the AI analysis?
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Let us know what was inaccurate, what the AI may have missed, or how it could be improved.
          </p>
        </div>

        {/* Feedback Input */}
        <div className="mt-4">
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Type your feedback..."
            className="h-28 w-full resize-none rounded-lg border border-foreground/15 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-red-500/40"
          />
        </div>

        {/* Action Buttons */}
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="h-9 rounded-lg border border-foreground/15 bg-background px-5 text-sm font-medium text-foreground hover:bg-accent"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            className="h-9 rounded-lg bg-red-500 px-5 text-sm font-semibold text-white hover:bg-red-500/90"
          >
            Submit Feedback
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}