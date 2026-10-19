import * as React from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"
import { findingsApi } from "@/lib/api"

export type AddCommentModalProps = {
  open: boolean
  onClose: () => void
  onSubmit?: (comment: string) => void
  orgSlug: string
  findingId?: string
}

export function AddCommentModal({ open, onClose, onSubmit, orgSlug, findingId }: AddCommentModalProps) {
  const [comment, setComment] = React.useState("")
  const [existingComments, setExistingComments] = React.useState<Array<{
    id: string
    content: string
    created_at: string
    author_name?: string
    role?: string
  }>>([])
  const [loadingComments, setLoadingComments] = React.useState(false)
  const textareaRef = React.useRef<HTMLTextAreaElement>(null)

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
    if (!open) {
      setComment("")
      setExistingComments([])
      return
    }
    
    // Fetch existing comments when modal opens
    if (findingId) {
      setLoadingComments(true)
      findingsApi.getComments(orgSlug, findingId)
        .then((comments) => {
          // Sort comments by created_at in ascending order (oldest first)
          const sorted = (comments as Array<{ created_at: string }>).sort((a, b) => {
            const timeA = new Date(a.created_at.endsWith("Z") ? a.created_at : a.created_at + "Z").getTime()
            const timeB = new Date(b.created_at.endsWith("Z") ? b.created_at : b.created_at + "Z").getTime()
            return timeA - timeB
          })
          setExistingComments(sorted as Array<{
            id: string
            content: string
            created_at: string
            author_name?: string
            role?: string
          }>)
        })
        .catch(() => {
          // Silently fail if comments can't be loaded
          setExistingComments([])
        })
        .finally(() => {
          setLoadingComments(false)
        })
    }
  }, [open, findingId, orgSlug])

  const handleSubmit = async () => {
    if (!comment.trim()) return
    await onSubmit?.(comment)
    setComment("")
    onClose() // Close the modal after submitting the comment
  }

  // Auto-resize textarea as user types
  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setComment(e.target.value)
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + "px"
    }
  }

  // Reset textarea height when modal opens/closes or comment is cleared
  React.useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height = "112px" // Default h-28 (7rem = 112px)
    }
  }, [open, comment === ""])

  if (!open || typeof document === "undefined") return null

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-md px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Add Comment"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="relative w-full max-w-[560px] max-h-[90vh] rounded-xl bg-card p-6 shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)] flex flex-col overflow-hidden"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 shrink-0">
          <div>
            <h2 className="text-lg font-bold text-foreground">Feedback</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Add a note or feedback specific to this finding.
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

        {/* Existing Comments */}
        {existingComments.length > 0 && (
          <div className="mt-5 min-h-0 flex-1 overflow-y-auto space-y-3 rounded-lg border border-foreground/10 bg-muted/30 p-3">
            {existingComments.map((c) => (
              <div key={c.id} className="space-y-1">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {c.author_name ? (
                    <span className="font-medium text-foreground">{c.author_name}</span>
                  ) : c.role ? (
                    <span className="font-medium text-foreground capitalize">{c.role}</span>
                  ) : null}
                  {(c.author_name || c.role) && <span>•</span>}
                  <span>{new Date(c.created_at.endsWith("Z") ? c.created_at : c.created_at + "Z").toLocaleString("en-US")}</span>
                </div>
                <div className="text-sm text-foreground">{c.content}</div>
              </div>
            ))}
          </div>
        )}

        {/* Comment Input */}
        <div className={`${existingComments.length > 0 ? "mt-4" : "mt-5"} shrink-0`}>
          <textarea
            ref={textareaRef}
            value={comment}
            onChange={handleTextareaChange}
            placeholder="Type your comment"
            className="w-full resize-none rounded-lg border border-foreground/15 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-[#5BC0EB]/40 overflow-hidden"
            style={{ minHeight: "112px" }}
          />
        </div>

        {/* Action Buttons */}
        <div className="mt-6 flex justify-end gap-3 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="h-9 rounded-lg border border-foreground/15 bg-background px-5 text-sm font-medium text-foreground hover:bg-accent"
          >
            Close
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!comment.trim() || loadingComments}
            className="h-9 rounded-lg bg-[#3EC682] px-5 text-sm font-semibold text-white hover:bg-[#3EC682]/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loadingComments ? "Submitting..." : "Submit"}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}