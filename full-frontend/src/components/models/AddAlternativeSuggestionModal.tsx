import * as React from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"

export type AddAlternativeSuggestionModalProps = {
  open: boolean
  onClose: () => void
  currentAiSuggestion: string
  onSubmit?: (userAlternative: string) => void
}

export function AddAlternativeSuggestionModal({
  open,
  onClose,
  currentAiSuggestion,
  onSubmit,
}: AddAlternativeSuggestionModalProps) {
  const [userAlternative, setUserAlternative] = React.useState("")

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
    if (!open) setUserAlternative("")
  }, [open])

  const handleSubmit = () => {
    onSubmit?.(userAlternative)
    onClose()
  }

  if (!open || typeof document === "undefined") return null

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-md px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Add Alternative Suggestion"
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
          <div>
            <h2 className="text-lg font-bold text-foreground">Add Alternative Suggestion</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Provide your own compliant alternative to the flagged content.
            </p>
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

        {/* Current AI Suggestion */}
        <div className="mt-5">
          <div className="text-sm font-semibold text-foreground">Current AI Suggestion:</div>
          <div className="mt-2 rounded-lg border border-[#B8D4F0] bg-[#F0F8FF] dark:border-blue-900/50 dark:bg-blue-950/30 px-3 py-3">
            <p className="text-sm leading-5 text-foreground">{currentAiSuggestion}</p>
          </div>
        </div>

        {/* User Input */}
        <div className="mt-5">
          <label className="text-sm font-semibold text-foreground">Your alternative suggestion</label>
          <textarea
            value={userAlternative}
            onChange={(e) => setUserAlternative(e.target.value)}
            placeholder="Enter your alternative suggestion"
            className="mt-2 h-28 w-full resize-none rounded-lg border border-foreground/15 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-[#5BC0EB]/40"
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
            className="h-9 rounded-lg bg-[#3EC682] px-5 text-sm font-semibold text-white hover:bg-[#3EC682]/90"
          >
            Submit
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}