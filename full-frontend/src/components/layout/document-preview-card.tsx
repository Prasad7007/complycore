import { cn } from "@/lib/utils"
import * as React from "react"

// ── Types ────────────────────────────────────────────────────────

export type DocumentStatus = "in-review" | "approved" | "rejected" | "conditional"

export type DocumentRule = {
  code: string
  label: string
  color?: string
}

export type DocumentPreviewCardProps = {
  /** Reviewer name shown in the header */
  reviewerName: string
  /** Sub-label under reviewer name */
  reviewerSubLabel?: string
  /** Document title inside the body */
  documentTitle?: string
  /** Paragraphs of document body text */
  paragraphs?: string[]
  /** Key benefits list (bullet points) */
  benefits?: string[]
  /** Status badge — controls badge style and shows/hides rules */
  status: DocumentStatus
  /** NI rules list — only shown when status is NOT "approved" */
  rules?: DocumentRule[]
  /** Hide the rules section entirely (e.g. after Claim Review) */
  hideRules?: boolean
  /** Called when status badge is clicked (optional) */
  onStatusClick?: () => void
  className?: string
  fileUrl?: string
  downloadUrl?: string
  fileName?: string
  downloadFileName?: string
  mime?: string
  hideReviewerHeader?: boolean
  viewOnly?: boolean
}

// ── Badge styles per status ───────────────────────────────────────

const statusConfig: Record<
  DocumentStatus,
  { label: string; className: string }
> = {
  "in-review": {
    label: "In Review",
    className: "border-[#FF8D28] bg-[#FF8D28]/5 text-[#FF8D28]",
  },
  approved: {
    label: "Approved",
    className: "border-emerald-500 bg-emerald-50 text-emerald-700",
  },
  rejected: {
    label: "Rejected",
    className: "border-red-400 bg-red-50 text-red-600",
  },
  conditional: {
    label: "Conditional",
    className: "border-amber-400 bg-amber-50 text-amber-700",
  },
}

// ── Avatar (initials) ─────────────────────────────────────────────

function Avatar({ name, size = 34 }: { name: string; size?: number }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
  return (
    <div
      className="grid shrink-0 place-items-center rounded-full bg-foreground/10 text-[10px] font-semibold text-foreground"
      style={{ width: size, height: size }}
    >
      {initials || "U"}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────

export function DocumentPreviewCard({
  reviewerName,
  reviewerSubLabel,
  documentTitle,
  paragraphs = [],
  benefits = [],
  status,
  rules = [],
  hideRules,
  onStatusClick,
  className,
  fileUrl,
  downloadUrl,
  fileName,
  downloadFileName,
  mime,
  hideReviewerHeader = false,
  viewOnly = false,
}: DocumentPreviewCardProps) {
  const badge = statusConfig[status]
  const showRules = !hideRules && status !== "approved" && rules.length > 0
  const viewerHeightClass = "flex-1 min-h-[600px] w-full"
  const [viewerLoading, setViewerLoading] = React.useState(false)

  React.useEffect(() => {
    setViewerLoading(Boolean(fileUrl))
  }, [fileUrl, fileName, mime])

  const renderFileViewer = () => {
    if (!fileUrl) return null

    const lowerMime = (mime || "").toLowerCase()
    const lowerName = (fileName || "").toLowerCase()

    // PDF viewer
    if (lowerMime.includes("pdf") || lowerName.endsWith(".pdf")) {
      return (
        <div className={`${viewerHeightClass} relative flex flex-col`}>
          {viewerLoading ? (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-card/95">
              <div className="h-7 w-7 animate-spin rounded-full border-2 border-[#128BDA]/20 border-t-[#128BDA]" />
              <p className="text-xs text-muted-foreground">Loading preview...</p>
            </div>
          ) : null}
          <iframe
            src={fileUrl ? `${fileUrl.split("#")[0]}#toolbar=1` : ""}
            title={fileName || "document"}
            className="h-full w-full flex-1"
            style={{ border: 0 }}
            onLoad={() => setViewerLoading(false)}
            onError={() => setViewerLoading(false)}
          />
        </div>
      )
    }

    // Image viewer
    if (lowerMime.startsWith("image/") || lowerName.match(/\.(png|jpe?g|webp)$/)) {
      return (
        <div className={`${viewerHeightClass} relative flex items-center justify-center`}>
          {viewerLoading ? (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-card/95">
              <div className="h-7 w-7 animate-spin rounded-full border-2 border-[#128BDA]/20 border-t-[#128BDA]" />
              <p className="text-xs text-muted-foreground">Loading preview...</p>
            </div>
          ) : null}
          <img
            src={fileUrl}
            alt={fileName}
            className="max-h-full max-w-full"
            onLoad={() => setViewerLoading(false)}
            onError={() => setViewerLoading(false)}
          />
        </div>
      )
    }

    // Fallback: view-only mode should never provide download/open links.
    if (viewOnly) {
      return (
        <div className="flex h-[200px] w-full items-center justify-center">
          <div className="text-center">
            <p className="text-sm font-medium text-foreground">Preview unavailable</p>
            <p className="mt-1 text-xs text-muted-foreground">
              This file cannot be previewed here yet.
            </p>
          </div>
        </div>
      )
    }

    // Fallback: provide open link (non-view-only surfaces)
    return (
      <div className="flex h-[160px] w-full items-center justify-center">
        <a href={downloadUrl || fileUrl} target="_blank" rel="noreferrer" className="text-sm font-medium text-sky-600">
          Open {downloadFileName || fileName || "file"}
        </a>
      </div>
    )
  }

  return (
    <div className={cn("flex flex-col min-h-0 flex-1 overflow-hidden rounded-xl border bg-card", className)}>

      {/* ── Reviewer header ── */}
      {!hideReviewerHeader ? (
        <div className="flex items-center justify-between gap-3 border-b px-5 py-3">
          <div className="flex items-center gap-3">
            <Avatar name={reviewerName} size={34} />
            <div>
              <div className="text-sm font-semibold text-foreground">{reviewerName}</div>
              {reviewerSubLabel && (
                <div className="text-xs text-muted-foreground">{reviewerSubLabel}</div>
              )}
            </div>
          </div>

          {onStatusClick ? (
            <button
              type="button"
              onClick={onStatusClick}
              className={cn(
                "inline-flex items-center rounded border px-2.5 py-0.5 text-xs font-medium transition-colors hover:bg-accent",
                badge.className
              )}
              aria-label={`Status: ${badge.label}`}
            >
              {badge.label}
            </button>
          ) : (
            <span
              className={cn(
                "inline-flex items-center rounded border px-2.5 py-0.5 text-xs font-medium",
                badge.className
              )}
            >
              {badge.label}
            </span>
          )}
        </div>
      ) : null}

      {/* ── Document body + rules (scrollable) ── */}
      <div className="min-h-0 flex-1 flex flex-col overflow-y-auto">
        <div className={`${fileUrl ? 'flex flex-col flex-1 min-h-0' : ''} px-5 pt-4 pb-3 text-sm leading-relaxed text-foreground/80 space-y-4`}>
          {documentTitle && (
            <p className="font-semibold text-foreground">{documentTitle}</p>
          )}

          {/* If a file URL is provided, show the file viewer instead of the static paragraphs */}
          {fileUrl ? (
            <div className="mt-2 flex flex-col flex-1 min-h-0">
              {renderFileViewer()}
            </div>
          ) : (
            paragraphs.map((para, i) => (
              <p key={i}>{para}</p>
            ))
          )}

          {benefits.length > 0 && (
            <div>
              <p className="font-medium text-foreground">Key Benefits:</p>
              <ul className="mt-1 space-y-0.5 pl-1">
                {benefits.map((b) => (
                  <li key={b} className="flex items-start gap-1.5">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-foreground/40" />
                    {b}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* ── NI 31-103 Rules — hidden when Approved ── */}
        {showRules ? (
          <div className="px-5 pt-5 pb-5">
            <p className="mb-2 text-xs font-semibold text-foreground">
              NI 31-103 Rules Triggered
            </p>
            <ul className="space-y-1">
              {rules.map((r, i) => (
                <li
                  key={i}
                  className={cn("text-xs", r.color ?? "text-muted-foreground")}
                >
                  <span className="font-semibold">{r.code}</span>{" "}
                  {r.label}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  )
}
