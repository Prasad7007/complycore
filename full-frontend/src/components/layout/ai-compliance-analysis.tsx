import * as React from "react"
import { AlertTriangle, ChevronDown, ThumbsDown, ThumbsUp, X, Check, MessageSquare, Ban } from "lucide-react"
import { createPortal } from "react-dom"

import { AddAlternativeSuggestionModal } from "@/components/models/AddAlternativeSuggestionModal"
import { AddCommentModal } from "@/components/models/AddCommentModal"
import { DislikeFeedbackModal } from "@/components/models/DislikeFeedbackModal"
import { cn } from "@/lib/utils"
import { findingsApi } from "@/lib/api"

export type AiSeverity = "High" | "Medium" | "Low"

/**
 * Deterministic pastel highlight palette — must exactly mirror backend _HIGHLIGHT_PALETTE.
 * Used to show a colored dot on each finding card matching the PDF annotation color.
 */
const HIGHLIGHT_PALETTE: string[] = [
  "#FFFF66", // bright yellow
  "#99FFFF", // bright cyan
  "#99FF99", // bright lime green
  "#FFB3CC", // bright pink
  "#CCCCFF", // bright lavender
]

export type AiComplianceFinding = {
  id: string
  /** Actual ai_findings.id UUID (used for suggestions/comments when card id is synthetic like claim-*) */
  primaryFindingId?: string
  severity: AiSeverity
  title: string
  summary: string
  rule: string
  /** When multiple rules violate one claim, list all rules; one card, one suggestion */
  rules?: string[]
  /**
   * When grouped by claim_id, we still need per-finding status/actions.
   * Each item is a real ai_findings row.
   */
  groupItems?: Array<{
    id: string
    label: string
    status: string
  }>
  location?: string
  /** Claim text from engine (same for all findings in a claim-wise group) */
  claimText?: string
  whyRisky?: string
  ruleRationale?: string
  suggestedAlternative?: string
  status?: string
  acceptedSuggestionId?: string | null
  findingCode?: string
  findingCodes?: string[]
}

export type AiComplianceAnalysisProps = {
  findings: AiComplianceFinding[]
  /** Tenant org slug for API paths under /orgs/:slug/... */
  orgSlug: string
  className?: string
  userRoles?: string[]
  workflowStage?: string
  reviewId?: string
  onFindingUpdate?: () => void | Promise<void>
  isClaimed?: boolean
  needsClaiming?: boolean
  /** Called when collapse button is clicked. When provided, shows collapse button in header. */
  onCollapseClick?: () => void
  /** Called when user clicks a page location link in a finding. */
  onLocationClick?: (target: { page: number; line?: number | null; rawLocation?: string }) => void
  /** Incremented by parent on every SSE event — triggers re-fetch of comments and suggestions. */
  refreshTrigger?: number
  /** Called whenever the count of accepted-but-suggestion-pending findings changes. Used by parent to gate the Approve button. */
  onPendingSuggestionsChange?: (count: number) => void
}

function severityStyles(severity: AiSeverity) {
  if (severity === "High") {
    return {
      badge: "border-red-200 bg-red-50 text-red-600 dark:border-red-800 dark:bg-red-950/50 dark:text-red-400",
      border: "border-red-200 dark:border-red-800",
      accent: "text-red-600 dark:text-red-400",
      whyBg: "bg-[#FEEBEB] border border-red-100 dark:bg-red-950/50 dark:border-red-800",
    }
  }
  if (severity === "Medium") {
    return {
      badge: "border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-800 dark:bg-orange-950/50 dark:text-orange-400",
      border: "border-orange-200 dark:border-orange-800",
      accent: "text-orange-600 dark:text-orange-400",
      whyBg: "bg-orange-50 border border-orange-100 dark:bg-orange-950/50 dark:border-orange-800",
    }
  }
  return {
    badge: "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/50 dark:text-sky-400",
    border: "border-sky-200 dark:border-sky-800",
    accent: "text-sky-600 dark:text-sky-400",
    whyBg: "bg-sky-50 border border-sky-100 dark:bg-sky-950/50 dark:border-sky-800",
  }
}

export function AiComplianceAnalysis({
  findings,
  orgSlug,
  className,
  userRoles = [],
  workflowStage = "",
  onFindingUpdate,
  isClaimed = false,
  needsClaiming = false,
  onCollapseClick,
  onLocationClick,
  refreshTrigger = 0,
  onPendingSuggestionsChange,
}: AiComplianceAnalysisProps) {
  const sortedFindings = React.useMemo(() => {
    const parsePageLine = (location?: string) => {
      const text = location || ""
      if (text === "Document Level") {
        return { page: Number.POSITIVE_INFINITY, line: Number.POSITIVE_INFINITY }
      }
      const pageMatch = /Page\s+(\d+)/i.exec(text)
      const lineMatch = /Line\s+(\d+)/i.exec(text)
      const page = pageMatch ? Number(pageMatch[1]) : Number.POSITIVE_INFINITY
      const line = lineMatch ? Number(lineMatch[1]) : Number.POSITIVE_INFINITY
      return { page, line }
    }

    return findings
      .map((f, idx) => {
        const p = parsePageLine(f.location)
        return { finding: f, idx, page: p.page, line: p.line }
      })
      .sort((a, b) => {
        if (a.page !== b.page) return a.page - b.page
        if (a.line !== b.line) return a.line - b.line
        return a.idx - b.idx
      })
      .map((x) => x.finding)
  }, [findings])

  // Keep UI dot color aligned with backend annotation color assignment:
  // backend assigns by original grouped-claim order, so we preserve that index here
  // even when cards are location-sorted for display.
  const originalIndexById = React.useMemo(() => {
    const map = new Map<string, number>()
    findings.forEach((f, idx) => map.set(f.id, idx))
    return map
  }, [findings])

  const [rating, setRating] = React.useState<"like" | "dislike" | null>(null)
  const [addAlternativeFinding, setAddAlternativeFinding] = React.useState<AiComplianceFinding | null>(null)
  const [addCommentFinding, setAddCommentFinding] = React.useState<AiComplianceFinding | null>(null)
  const [dislikeFeedbackOpen, setDislikeFeedbackOpen] = React.useState(false)
  /** Tracks finding keys whose suggestions+comments have already been fetched this mount.
   *  Prevents re-firing N×(getSuggestions+getComments) on every findings prop update
   *  caused by refreshData() after a flag action. */
  const fetchedKeysRef = React.useRef<Set<string>>(new Set())

  const [actionLoadingMap, setActionLoadingMap] = React.useState<Record<string, boolean>>({})

  const setActionKeyLoading = React.useCallback((keys: string | string[], isLoading: boolean) => {
    const keyList = Array.isArray(keys) ? keys : [keys]
    setActionLoadingMap((prev) => {
      const next = { ...prev }
      keyList.forEach((k) => {
        if (isLoading) {
          next[k] = true
        } else {
          delete next[k]
        }
      })
      return next
    })
  }, [])

  const isKeyLoading = React.useCallback((key?: string | string[] | null) => {
    if (!key) return false
    if (Array.isArray(key)) {
      return key.some((k) => Boolean(actionLoadingMap[k]))
    }
    return Boolean(actionLoadingMap[key])
  }, [actionLoadingMap])

  const [userSuggestions, setUserSuggestions] = React.useState<Record<string, unknown[]>>({})
  const [expandedFindings, setExpandedFindings] = React.useState<Record<string, boolean>>({})
  const [error, setError] = React.useState<string | null>(null)
  const [inlineEditorOpen, setInlineEditorOpen] = React.useState<Set<string>>(new Set())
  const [inlineEditorDraft, setInlineEditorDraft] = React.useState<Record<string, string>>({})
  const [editingSuggestionId, setEditingSuggestionId] = React.useState<Record<string, string | null>>({})
  
  const [acceptAltConfirm, setAcceptAltConfirm] = React.useState<{findingId: string, choice: "ai" | "mkt", isGroup: boolean, groupIds: string[], marketingSuggestionId?: string} | null>(null)
  const [selectedAltChoice, setSelectedAltChoice] = React.useState<Record<string, "ai" | "mkt">>({})
  
  const [findingComments, setFindingComments] = React.useState<Record<string, Array<any>>>({})
  const [dismissModalFindingId, setDismissModalFindingId] = React.useState<string | null>(null)
  const [dismissModalGroupIds, setDismissModalGroupIds] = React.useState<string[]>([])
  const [dismissReason, setDismissReason] = React.useState<string>("")
  const [dismissOtherNote, setDismissOtherNote] = React.useState<string>("")

  // Reject Modal State
  const [rejectModalFindingId, setRejectModalFindingId] = React.useState<string | null>(null)
  const [rejectModalGroupIds, setRejectModalGroupIds] = React.useState<string[]>([])
  const [rejectReason, setRejectReason] = React.useState<string>("")
  const [commentInput, setCommentInput] = React.useState<Record<string, string>>({})
  const [acceptedChoice, setAcceptedChoice] = React.useState<Record<string, "ai" | "mkt">>({})
  /** Tracks findings accepted this session that still need a suggestion selected (hard gate for Approve). */
  const [pendingSuggestionIds, setPendingSuggestionIds] = React.useState<Set<string>>(new Set())

  // Notify parent so it can disable the Approve button until all pending are resolved
  React.useEffect(() => {
    onPendingSuggestionsChange?.(pendingSuggestionIds.size)
  }, [pendingSuggestionIds.size, onPendingSuggestionsChange])

  React.useEffect(() => {
    setExpandedFindings((prev) => {
      const next: Record<string, boolean> = {}
      sortedFindings.forEach((finding) => {
        next[finding.id] = prev[finding.id] ?? true
      })
      return next
    })
  }, [sortedFindings])

  const isMarketingUser = userRoles.includes("marketing")
  const isComplianceUser = userRoles.includes("compliance")
  const isMarketingStage = workflowStage === "marketing_review"
  const isComplianceStage = workflowStage === "compliance_review"

  // Check if user can interact (must be claimed if stage requires claiming)
  const canInteract = needsClaiming ? isClaimed : true

  // Marketing users can add/edit suggestions during marketing OR compliance stages
  const showMarketingButtons = isMarketingUser && (isMarketingStage || isComplianceStage)
  // Show buttons for compliance users in compliance_review stage
  const showComplianceButtons = isComplianceUser && isComplianceStage && canInteract

  React.useEffect(() => {
    if (!showComplianceButtons) {
      setAcceptAltConfirm(null)
      setSelectedAltChoice({})
    }
  }, [showComplianceButtons])

  // Match action button sizing to the severity badge (top-left pill)
  const actionBtnBase =
    "inline-flex min-h-[34px] items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-semibold"

  const fetchComments = React.useCallback((key: string) => {
    findingsApi.getComments(orgSlug, key).then(comments => {
      setFindingComments(prev => ({
        ...prev,
        [key]: (comments as any[]).sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
      }))
    }).catch(console.error)
  }, [orgSlug])

  // Only fetch suggestions + comments for finding keys that haven't been loaded yet.
  // This prevents re-firing N×(getSuggestions+getComments) on every prop update
  // triggered by refreshData() after a flag action — the finding IDs don't change,
  // so fetchedKeysRef skips them and zero extra requests are made.
  React.useEffect(() => {
    const keysToFetch = sortedFindings
      .map((f) => f.primaryFindingId || f.id)
      .filter((key) => !fetchedKeysRef.current.has(key))

    keysToFetch.forEach((key) => {
      fetchedKeysRef.current.add(key)
      findingsApi
        .getSuggestions(orgSlug, key)
        .then((suggestions) => {
          setUserSuggestions((prev) => ({
            ...prev,
            [key]: (suggestions as unknown[]) || [],
          }))
        })
        .catch((err) => {
          console.error("Failed to fetch suggestions:", err)
          setUserSuggestions((prev) => ({ ...prev, [key]: [] }))
        })
      fetchComments(key)
    })
  }, [sortedFindings, orgSlug, fetchComments])

  // When refreshTrigger changes (explicit panel reset, e.g. after a user adds a comment),
  // clear the cache so the next render re-fetches fresh data for all findings.
  React.useEffect(() => {
    if (refreshTrigger === 0) return
    fetchedKeysRef.current = new Set()
  }, [refreshTrigger])

  const handleAccept = async (findingId: string, groupIds: string[] = []) => {
    const keysToLock = Array.from(new Set([findingId, ...groupIds]))
    if (keysToLock.some((k) => actionLoadingMap[k])) return
    setActionKeyLoading(keysToLock, true)
    try {
      console.log("Accepting finding:", findingId)
      const result = await findingsApi.acceptFinding(orgSlug, findingId)
      console.log("Accept result:", result)
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      console.error("Accept error:", error)
      const message =
        error instanceof Error ? error.message : "Failed to accept finding"
      setError(message)
    } finally {
      setActionKeyLoading(keysToLock, false)
    }
  }

  const handleReject = async (findingId: string, reason?: string, groupIds: string[] = []) => {
    const keysToLock = Array.from(new Set([findingId, ...groupIds]))
    if (keysToLock.some((k) => actionLoadingMap[k])) return
    setActionKeyLoading(keysToLock, true)
    try {
      console.log("Rejecting finding:", findingId, reason)
      const result = await findingsApi.rejectFinding(orgSlug, findingId, reason)
      console.log("Reject result:", result)
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      console.error("Reject error:", error)
      const message =
        error instanceof Error ? error.message : "Failed to reject finding"
      setError(message)
    } finally {
      setActionKeyLoading(keysToLock, false)
    }
  }

  const handleDismissMany = async (findingIds: string[]) => {
    const ids = Array.from(new Set(findingIds.filter(Boolean)))
    if (ids.length === 0) return
    if (ids.some((k) => actionLoadingMap[k])) return
    setActionKeyLoading(ids, true)
    try {
      const finalReason = dismissReason === "Other" 
        ? `Other: ${dismissOtherNote}` 
        : dismissReason;
      await Promise.all(ids.map((id) => findingsApi.dismissFinding(orgSlug, id, finalReason)))
      setDismissModalFindingId(null)
      setDismissModalGroupIds([])
      setDismissReason("")
      setDismissOtherNote("")
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : "Failed to dismiss finding")
    } finally {
      setActionKeyLoading(ids, false)
    }
  }

  const handlePostComment = async (findingId: string) => {
    const text = commentInput[findingId]
    if (!text?.trim()) return
    const key = `comment-${findingId}`
    if (actionLoadingMap[key]) return
    setActionKeyLoading(key, true)
    try {
      await findingsApi.addComment(orgSlug, findingId, text.trim())
      setCommentInput(prev => ({ ...prev, [findingId]: "" }))
      fetchComments(findingId)
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : "Failed to add comment")
    } finally {
      setActionKeyLoading(key, false)
    }
  }

  const handleSaveInlineSuggestion = async (findingId: string) => {
    const text = inlineEditorDraft[findingId]
    if (!text?.trim()) {
      setError("Please enter a suggestion")
      return
    }
    const key = `sugg-${findingId}`
    if (actionLoadingMap[key]) return
    setActionKeyLoading(key, true)
    try {
      const existingSuggestionId = editingSuggestionId[findingId]
      if (existingSuggestionId) {
        // Editing an existing suggestion — call the PUT endpoint
        await findingsApi.editSuggestion(orgSlug, findingId, existingSuggestionId, text.trim())
      } else {
        // Adding a brand new suggestion
        await findingsApi.addSuggestion(orgSlug, findingId, text.trim())
      }
      setInlineEditorOpen(prev => {
        const next = new Set(prev)
        next.delete(findingId)
        return next
      })
      setEditingSuggestionId(prev => ({ ...prev, [findingId]: null }))
      const suggestions = await findingsApi.getSuggestions(orgSlug, findingId)
      setUserSuggestions(prev => ({ ...prev, [findingId]: (suggestions as unknown[]) || [] }))
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : "Failed to save suggestion")
    } finally {
      setActionKeyLoading(key, false)
    }
  }

  const handleAcceptThis = async (
    findingId: string,
    choice: "ai" | "mkt",
    isGroup: boolean,
    groupIds: string[],
    marketingSuggestionId?: string
  ) => {
    const keysToLock = Array.from(new Set([findingId, ...(groupIds || [])]))
    if (keysToLock.some((k) => actionLoadingMap[k])) return
    setActionKeyLoading(keysToLock, true)
    try {
      const suggestionId = choice === "mkt" ? marketingSuggestionId : undefined
      if (isGroup && groupIds.length > 0) {
        await Promise.all(groupIds.map((id) =>
          // Marketing suggestions are attached to one finding only (the primary).
          // Pass suggestionId only to that finding; accept others without it.
          findingsApi.acceptFinding(orgSlug, id, id === findingId ? suggestionId : undefined)
        ))
      } else {
        await findingsApi.acceptFinding(orgSlug, findingId, suggestionId)
      }
      setAcceptedChoice((prev) => ({ ...prev, [findingId]: choice }))
      setSelectedAltChoice((prev) => {
        const next = { ...prev }
        delete next[findingId]
        return next
      })
      // Suggestion has been selected — remove from pending gate
      setPendingSuggestionIds((prev) => {
        const next = new Set(prev)
        next.delete(findingId)
        return next
      })
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : "Failed to accept finding")
    } finally {
      setActionKeyLoading(keysToLock, false)
    }
  }

  const handleAcceptMany = async (findingIds: string[]) => {
    const ids = Array.from(new Set(findingIds.filter(Boolean)))
    if (ids.length === 0) return
    if (ids.some((k) => actionLoadingMap[k])) return
    setActionKeyLoading(ids, true)
    try {
      await Promise.all(ids.map((id) => findingsApi.acceptFinding(orgSlug, id)))
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to accept findings"
      setError(message)
    } finally {
      setActionKeyLoading(ids, false)
    }
  }

  const handleRejectMany = async (findingIds: string[], reason?: string) => {
    const ids = Array.from(new Set(findingIds.filter(Boolean)))
    if (ids.length === 0) return
    if (ids.some((k) => actionLoadingMap[k])) return
    setActionKeyLoading(ids, true)
    try {
      await Promise.all(ids.map((id) => findingsApi.rejectFinding(orgSlug, id, reason)))
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to reject findings"
      setError(message)
    } finally {
      setActionKeyLoading(ids, false)
    }
  }

  const handleAddSuggestion = async (userAlternative: string) => {
    if (!addAlternativeFinding) return
    if (!userAlternative.trim()) {
      setError("Please enter a suggestion")
      return
    }
    const targetFindingId = addAlternativeFinding.primaryFindingId || addAlternativeFinding.id
    if (actionLoadingMap[targetFindingId]) return
    setActionKeyLoading(targetFindingId, true)
    try {
      await findingsApi.addSuggestion(orgSlug, targetFindingId, userAlternative.trim())
      
      // If compliance user adds a suggestion, automatically accept the finding
      if (showComplianceButtons) {
        await findingsApi.acceptFinding(orgSlug, targetFindingId)
      }

      setAddAlternativeFinding(null)
      // Refresh suggestions after adding
      const suggestions = await findingsApi.getSuggestions(orgSlug, targetFindingId)
      setUserSuggestions((prev) => ({
        ...prev,
        [targetFindingId]: (suggestions as unknown[]) || []
      }))
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      const message =
        error instanceof Error ? error.message : "Failed to add suggestion"
      setError(message)
    } finally {
      setActionKeyLoading(targetFindingId, false)
    }
  }

  const handleAddComment = async (comment: string) => {
    if (!addCommentFinding) return
    if (!comment.trim()) {
      setError("Please enter a comment")
      return
    }
    const targetId = addCommentFinding.primaryFindingId || addCommentFinding.id
    if (actionLoadingMap[targetId]) return
    setActionKeyLoading(targetId, true)
    try {
      await findingsApi.addComment(orgSlug, targetId, comment.trim())
      // Don't close modal - let it stay open to show the new comment
      // The modal will refresh comments after submission
      if (onFindingUpdate) await onFindingUpdate()
    } catch (error: unknown) {
      const message =
        error instanceof Error ? error.message : "Failed to add comment"
      setError(message)
    } finally {
      setActionKeyLoading(targetId, false)
    }
  }


  const renderAltBox = (
    title: string,
    contentText: string,
    state: string,
    picker?: { show: boolean; picked: boolean; onPick: () => void },
    onEdit?: () => void,
    isMarketingAlt?: boolean
  ) => {
    let boxClasses = "rounded-lg border px-3 py-2 transition-all "
    let titleClasses = "text-[11px] font-semibold flex-1 "
    let rightElement = null

    if (state === "accepted") {
      boxClasses += "bg-green-50 border-green-200 dark:bg-green-950/50 dark:border-green-800"
      titleClasses += "text-green-700 dark:text-green-400"
      rightElement = <span className="inline-flex items-center gap-1 rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-700 dark:bg-green-900/50 dark:text-green-400"><Check className="h-3 w-3" /> Accepted by Compliance</span>
    } else if (state === "rejected") {
      boxClasses += "bg-red-50 border-red-200 opacity-50 dark:bg-red-950/50 dark:border-red-800"
      titleClasses += "text-red-700 dark:text-red-400"
      if (picker?.show && !picker.picked) {
        rightElement = (
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 dark:bg-red-900/50 dark:text-red-400">Rejected</span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                picker.onPick()
              }}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-gray-300 bg-white px-2 py-1 text-[10px] font-bold text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              Accept this
            </button>
          </div>
        )
      } else {
        rightElement = <span className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700 dark:bg-red-900/50 dark:text-red-400">Rejected</span>
      }
    } else if (state === "voided") {
      boxClasses += "bg-gray-50 border-gray-200 opacity-55 dark:bg-gray-800/50 dark:border-gray-700"
      titleClasses += "text-gray-500 dark:text-gray-400"
      rightElement = <span className="inline-flex items-center gap-1 rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600 dark:bg-gray-700 dark:text-gray-300">No change needed</span>
    } else {
      boxClasses += isMarketingAlt ? "bg-[#F0F8FF] border-[#B8D4F0] dark:bg-sky-950/50 dark:border-sky-800" : "bg-[#F0F8FF] border-[#B8D4F0] dark:bg-sky-950/50 dark:border-sky-800"
      titleClasses += "text-[#1F4ED8] dark:text-[#60A5FA]"
      if (picker?.show) {
        rightElement = picker.picked ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-900/50 dark:text-blue-400">
            <Check className="h-3 w-3" /> Selected
          </span>
        ) : (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              picker.onPick()
            }}
            className="inline-flex shrink-0 items-center gap-1 rounded border border-green-600 bg-green-50 px-2 py-1 text-[10px] font-bold text-green-700 shadow-sm hover:bg-green-100 dark:border-green-500 dark:bg-green-950/50 dark:text-green-400 dark:hover:bg-green-900/50"
          >
            Accept this
          </button>
        )
      } else if (onEdit) {
        rightElement = (
          <button onClick={onEdit} className="shrink-0 text-[10px] font-medium text-blue-600 hover:underline dark:text-blue-400">Edit</button>
        )
      }
    }

    return (
      <div className={boxClasses}>
        <div className="flex items-center justify-between mb-1 gap-2">
          <div className={titleClasses}>{title}</div>
          {rightElement}
        </div>
        <div className="text-[11px] leading-4 text-muted-foreground whitespace-pre-wrap">{contentText}</div>
      </div>
    )
  }

  return (
    <div className={cn("compliance-panel flex h-full min-h-0 min-w-0 flex-col overflow-hidden", className)}>
      {/* Panel header - fixed, does not scroll */}
      <div className="panel-header flex shrink-0 items-center justify-between gap-3 pb-3">
        <span className="text-xs font-semibold text-foreground">AI Compliance Analysis</span>
        {onCollapseClick ? (
          <button
            type="button"
            onClick={onCollapseClick}
            className="shrink-0"
            aria-label="Collapse panel"
          >
            <img
              src="/documents/collapsibleIcon.svg"
              alt="Collapse"
              className="h-6 w-6 dark:invert dark:opacity-90"
              width={24}
              height={24}
            />
          </button>
        ) : null}
      </div>

      {/* AI Warning Banner */}
      <div className="mb-4 shrink-0 rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-[11px] leading-relaxed text-amber-600 dark:text-amber-400 flex items-start gap-2 shadow-sm">
        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
        <div>
          <strong>AI Disclaimer:</strong> AI-generated analysis is intended to assist the review process and should not replace professional compliance judgment. Users remain responsible for the final review and approval of all marketing materials.
        </div>
      </div>

      {error && (
        <div className="mx-4 mb-2 shrink-0 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Panel content — scrollable; Rate AI Analysis stays at bottom */}
      <div className="panel-content-scroll activity-scroll min-h-0 flex-1 space-y-4 overflow-x-hidden overflow-y-auto pr-2">

        {sortedFindings.map((f, findingIndex) => {
          const s = severityStyles(f.severity)
          const normalizedStatus = String(f.status || "").trim().toLowerCase()
          const isResolved = normalizedStatus === "accepted" || normalizedStatus === "rejected" || normalizedStatus === "dismissed"
          const isExpanded = expandedFindings[f.id] ?? true
          const groupItems = (f.groupItems || []).map((it) => ({
            ...it,
            status: String(it.status || "").trim().toLowerCase(),
          }))
          const groupIds = groupItems.map((it) => it.id).filter(Boolean)
          const backendColorIdx = originalIndexById.get(f.id) ?? findingIndex
          const highlightColor = HIGHLIGHT_PALETTE[backendColorIdx % HIGHLIGHT_PALETTE.length]

          const findingKey = f.primaryFindingId || f.id
          const suggestionsList = userSuggestions[findingKey] as any[] | undefined
          const hasMarketingAlt = suggestionsList && suggestionsList.length > 0
          const marketingAlt = hasMarketingAlt
            ? (f.acceptedSuggestionId
                ? suggestionsList.find((s) => String(s.id) === String(f.acceptedSuggestionId)) ??
                  suggestionsList[0]
                : suggestionsList[0])
            : null
          
          const comments = findingComments[findingKey] || []
          
          const isDismissed = normalizedStatus === "dismissed"
          const isAccepted = normalizedStatus === "accepted"
          const isRejected = normalizedStatus === "rejected"
          // needsSuggestionPick: accepted this session but suggestion not yet chosen
          const needsSuggestionPick = pendingSuggestionIds.has(findingKey) && showComplianceButtons
          const pickedAlt = selectedAltChoice[findingKey]

          let aiAltState = "default"
          let mktAltState = "default"
          
          if (isDismissed) {
            aiAltState = "voided"
            if (hasMarketingAlt) mktAltState = "voided"
          } else if (isRejected) {
            aiAltState = "rejected"
            if (hasMarketingAlt) mktAltState = "rejected"
          } else if (isAccepted && !needsSuggestionPick) {
            // Fully resolved — show which suggestion was accepted
            const choice =
              acceptedChoice[findingKey] ??
              (f.acceptedSuggestionId ? "mkt" : "ai")
            if (choice === "ai") {
              aiAltState = "accepted"
              if (hasMarketingAlt) mktAltState = "rejected"
            } else {
              aiAltState = "rejected"
              mktAltState = "accepted"
            }
          } else if (pickedAlt) {
            // User previewed a choice but hasn't confirmed yet
            if (pickedAlt === "ai") {
              mktAltState = "rejected"
            } else if (pickedAlt === "mkt") {
              aiAltState = "rejected"
            }
          }
          // else: default — pickers visible (covers needsSuggestionPick with no pickedAlt yet)

          return (
            <div
              key={f.id}
              className={cn(
                "relative z-10 flex flex-col overflow-hidden rounded-xl border bg-card p-4",
                s.border
              )}
              style={{ pointerEvents: "auto" }}
            >
              <div className="flex w-full items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-semibold",
                      s.badge
                    )}
                  >
                    <AlertTriangle className={cn("h-3.5 w-3.5", s.accent)} />
                    {f.severity}
                  </span>

                  {isResolved && (
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-semibold shadow-sm",
                        normalizedStatus === "accepted"
                          ? "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800"
                          : normalizedStatus === "rejected"
                          ? "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-400 dark:border-red-800"
                          : "bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700"
                      )}
                    >
                      {normalizedStatus === "accepted" ? "Accepted by Compliance" : normalizedStatus === "rejected" ? "Rejected" : "Dismissed"}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setExpandedFindings((prev) => ({
                      ...prev,
                      [f.id]: !isExpanded,
                    }))
                  }
                  className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  aria-label={isExpanded ? "Collapse finding" : "Expand finding"}
                  aria-expanded={isExpanded}
                >
                  <ChevronDown
                    className={cn("h-4 w-4 transition-transform duration-200", isExpanded && "rotate-180")}
                  />
                </button>
              </div>

              {isExpanded ? (
              <>
              <div className="shrink-0">
              <div className="mt-3">
                  {f.claimText && (
                    <div className="mb-3">
                      <div className="text-[11px] font-semibold text-foreground mb-1">Claim</div>
                      <div className={cn(
                        "rounded border border-foreground/10 bg-muted/30 px-2 py-1.5 text-[11px] leading-4 text-foreground",
                        isDismissed && "line-through text-muted-foreground opacity-70"
                      )}>
                        {f.claimText}
                      </div>
                      {!isResolved && showComplianceButtons && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            setDismissModalFindingId(findingKey)
                            setDismissModalGroupIds(groupIds)
                          }}
                          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-red-500/25 bg-red-500/[0.07] px-3.5 py-2.5 text-[11px] font-semibold text-red-600 transition-colors hover:bg-red-500/[0.13] dark:border-red-500/30 dark:bg-red-950/30 dark:text-red-400 dark:hover:bg-red-950/50"
                        >
                          <Ban className="h-3.5 w-3.5 shrink-0" /> Dismiss claim
                        </button>
                      )}
                    </div>
                  )}
                  
                  <div className="text-xs font-semibold text-foreground">{f.title}</div>
                  
                  <div className="mt-1.5 flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                    {f.findingCodes && f.findingCodes.length > 0 ? (
                      <span className="inline-flex items-center gap-1 rounded-md border border-foreground/10 bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                        <span className="font-semibold">Code{f.findingCodes.length > 1 ? "s" : ""}:</span>
                        <span className="font-mono">{f.findingCodes.join(", ")}</span>
                      </span>
                    ) : f.findingCode && (
                      <span className="inline-flex items-center gap-1 rounded-md border border-foreground/10 bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                        <span className="font-semibold">Code:</span>
                        <span className="font-mono">{f.findingCode}</span>
                      </span>
                    )}
                    {f.location && f.location !== "Document Level" && (() => {
                      const pageMatch = /(?:page|pg)\s*[#:,-]?\s*(\d+)/i.exec(f.location || "")
                      const lineMatch = /(?:line|ln)\s*[#:,-]?\s*(\d+)/i.exec(f.location || "")
                      const pageNum = pageMatch ? Number(pageMatch[1]) : NaN
                      const lineNum = lineMatch ? Number(lineMatch[1]) : null
                      const canJump = Number.isFinite(pageNum) && pageNum > 0 && !!onLocationClick

                      let locationLabel = pageMatch ? `Page ${pageNum}` : f.location.split("·")[0].trim()
                      if (lineNum) locationLabel += `, Line ${lineNum}`

                      return (
                        <button
                          type="button"
                          disabled={!canJump}
                          onClick={(e) => {
                            e.stopPropagation()
                            if (canJump) {
                              onLocationClick?.({
                                page: pageNum,
                                line: lineNum,
                                rawLocation: f.location,
                              })
                            }
                          }}
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[10px] font-semibold transition-colors",
                            canJump
                              ? "border-[#128BDA]/30 bg-[#128BDA]/[0.07] text-[#128BDA] hover:bg-[#128BDA]/[0.14] cursor-pointer"
                              : "border-foreground/10 bg-muted/40 text-muted-foreground cursor-default"
                          )}
                          title={canJump ? `Jump to ${locationLabel} in document` : f.location}
                        >
                          <span
                            className="inline-block h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-black/10"
                            style={{ backgroundColor: highlightColor }}
                          />
                          <img
                            src="/documents/loactionIcon.svg"
                            alt=""
                            className="h-3 w-3 shrink-0"
                            width={12}
                            height={12}
                          />
                          <span>{locationLabel}</span>
                          {canJump && (
                            <svg className="h-2.5 w-2.5 shrink-0" viewBox="0 0 12 12" fill="none">
                              <path d="M3 9L9 3M9 3H4M9 3V8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                            </svg>
                          )}
                        </button>
                      )
                    })()}
                    {f.location === "Document Level" && (
                      <span className="inline-flex items-center gap-1 rounded-md border border-foreground/10 bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                        <img
                          src="/documents/loactionIcon.svg"
                          alt=""
                          className="h-3 w-3 shrink-0 opacity-50"
                          width={12}
                          height={12}
                        />
                        <span>Document Level</span>
                      </span>
                    )}
                    </div>
                  </div>

                  {!f.claimText && (
                    <div className="mt-1 text-[11px] leading-4 text-muted-foreground">{f.summary}</div>
                  )}
                  
                  <div className="mt-2 flex flex-col gap-1.5">
                    {(f.rules && f.rules.length > 0 ? f.rules : f.rule ? [f.rule] : []).map((r, i) => (
                      <span
                        key={i}
                        className="inline-flex w-fit max-w-full rounded-md border border-[#1F4ED8]/20 bg-[#1F4ED8]/[0.06] px-2.5 py-1 text-[11px] font-medium leading-relaxed text-[#1F4ED8] dark:border-[#1F4ED8]/30 dark:bg-[#1F4ED8]/20 dark:text-[#60A5FA]"
                      >
                        {r}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <div className="mt-4 flex flex-col">
                  <div className="space-y-3">
                    {(f.summary || f.whyRisky) && !f.claimText ? (
                      <div className={cn("rounded-lg px-3 py-2", s.whyBg)}>
                        <div className={cn("text-[11px] font-semibold", s.accent)}>▲ Why This Is Risky</div>
                        <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
                          {f.summary || f.whyRisky}
                        </div>
                      </div>
                    ) : f.whyRisky ? (
                    <div className={cn("rounded-lg px-3 py-2", s.whyBg)}>
                      <div className={cn("text-[11px] font-semibold", s.accent)}>▲ Why This Is Risky</div>
                      <div className="mt-1 text-[11px] leading-4 text-muted-foreground">{f.whyRisky}</div>
                    </div>
                  ) : null}

                  {f.suggestedAlternative ? (
                    renderAltBox(
                      "AI Suggested Alternative",
                      f.suggestedAlternative,
                      aiAltState,
                      needsSuggestionPick
                        ? (pickedAlt === "mkt"
                            ? undefined
                            : {
                                show: true,
                                picked: pickedAlt === "ai",
                                onPick: () =>
                                  setAcceptAltConfirm({
                                    findingId: findingKey,
                                    choice: "ai",
                                    isGroup: groupItems.length > 0,
                                    groupIds: groupIds
                                  })
                              })
                        : undefined,
                      undefined,
                      false
                    )
                  ) : null}

                  {marketingAlt && !inlineEditorOpen.has(findingKey) ? (
                    renderAltBox(
                      "Marketing Suggested Alternative",
                      (marketingAlt as any).text || "",
                      mktAltState,
                      needsSuggestionPick
                        ? (pickedAlt === "ai"
                            ? undefined
                            : {
                                show: true,
                                picked: pickedAlt === "mkt",
                                onPick: () =>
                                  setAcceptAltConfirm({
                                    findingId: findingKey,
                                    choice: "mkt",
                                    isGroup: groupItems.length > 0,
                                    groupIds: groupIds,
                                    marketingSuggestionId: (marketingAlt as any).id
                                  })
                              })
                        : undefined,
                      showMarketingButtons && !isResolved && !needsSuggestionPick ? () => {
                        setInlineEditorOpen(prev => new Set(prev).add(findingKey))
                        setInlineEditorDraft(prev => ({ ...prev, [findingKey]: (marketingAlt as any).text || "" }))
                        setEditingSuggestionId(prev => ({ ...prev, [findingKey]: (marketingAlt as any).id || null }))
                      } : undefined,
                      true
                    )
                  ) : null}

                  {inlineEditorOpen.has(findingKey) && showMarketingButtons && !isResolved && (
                    <div className="rounded-lg border border-foreground/15 bg-background p-3 shadow-sm">
                      <textarea
                        placeholder="Write your alternative wording…"
                        value={inlineEditorDraft[findingKey] || ""}
                        onChange={(e) => setInlineEditorDraft(prev => ({ ...prev, [findingKey]: e.target.value }))}
                        className="min-h-[60px] w-full resize-y rounded-md border border-foreground/15 bg-background px-2.5 py-2 text-[11px] outline-none placeholder:text-muted-foreground focus:border-[#5BC0EB] focus:ring-1 focus:ring-[#5BC0EB]"
                      />
                      <div className="mt-2 flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setInlineEditorOpen(prev => {
                              const next = new Set(prev)
                              next.delete(findingKey)
                              return next
                            })
                            setEditingSuggestionId(prev => ({ ...prev, [findingKey]: null }))
                          }}
                          className="rounded border border-foreground/15 px-3 py-1.5 text-[10px] font-medium text-foreground hover:bg-muted"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          disabled={!inlineEditorDraft[findingKey]?.trim() || isKeyLoading(`sugg-${findingKey}`)}
                          onClick={() => handleSaveInlineSuggestion(findingKey)}
                          className="rounded bg-[#128BDA] px-3 py-1.5 text-[10px] font-semibold text-white hover:bg-[#128BDA]/90 disabled:opacity-50"
                        >
                          {isKeyLoading(`sugg-${findingKey}`) ? "Saving..." : "Save suggestion"}
                        </button>
                      </div>
                    </div>
                  )}

                  {showMarketingButtons && !hasMarketingAlt && !inlineEditorOpen.has(findingKey) && !isResolved && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setInlineEditorOpen(prev => new Set(prev).add(findingKey))
                        setInlineEditorDraft(prev => ({ ...prev, [findingKey]: "" }))
                      }}
                      className={cn(
                        "w-full border border-foreground/15 bg-card text-foreground hover:bg-muted font-semibold",
                        actionBtnBase
                      )}
                      style={{ fontFamily: "Inter, sans-serif" }}
                    >
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="h-3.5 w-3.5 shrink-0 text-[#128BDA]" xmlns="http://www.w3.org/2000/svg"><path d="M7 2.91666V11.0833M2.91666 7H11.0833" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                      <span>Add Alternative Suggestion</span>
                    </button>
                  )}

                  </div>

                  {/* Feedback Thread */}
                  <div className="mt-4 rounded-lg border border-[#F3DDC2] bg-[#FDF3E8] p-3 dark:border-orange-900/50 dark:bg-orange-950/20">
                    <div className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold text-[#D97A1F] dark:text-orange-400">
                      <MessageSquare className="h-3.5 w-3.5" />
                      Feedback
                    </div>
                    
                    <div className="mb-3 flex flex-col gap-2 max-h-[200px] overflow-y-auto pr-2 activity-scroll">
                      {comments.length === 0 ? (
                        <div className="text-[11px] italic text-muted-foreground">No messages yet — open for discussion.</div>
                      ) : (
                        comments.map((c: any, i: number) => {
                          const resolvedRoles = (() => {
                            if (!c.role) return ["user"]
                            const roles = c.role.split(",").map((p: any) => p.trim().toLowerCase()).filter(Boolean)
                            if (roles.length === 0) return ["user"]
                            let unique = Array.from(new Set(roles)) as string[]
                            // Move super_admin to end so operational role appears first
                            if (unique.includes("super_admin") && unique.length > 1) {
                              unique = [...unique.filter((u) => u !== "super_admin"), "super_admin"]
                            }
                            return unique
                          })()

                          const roleStyles: Record<string, { label: string; border: string; bg: string; badge: string }> = {
                            marketing: {
                              label: "Marketing",
                              border: "border-l-2 border-[#24A148] dark:border-[#24A148]",
                              bg: "bg-[#E9F6ED] dark:bg-[#123220]",
                              badge: "bg-[#24A148] text-white",
                            },
                            sme: {
                              label: "SME",
                              border: "border-l-2 border-[#5BC0EB] dark:border-[#5BC0EB]",
                              bg: "bg-[#EFF9FD] dark:bg-[#153049]",
                              badge: "bg-[#5BC0EB] text-slate-900",
                            },
                            compliance: {
                              label: "Compliance",
                              border: "border-l-2 border-[#F1C21B] dark:border-[#F1C21B]",
                              bg: "bg-[#FEF9E8] dark:bg-[#3a2f11]",
                              badge: "bg-[#F1C21B] text-slate-900",
                            },
                            super_admin: {
                              label: "Super Admin",
                              border: "border-l-2 border-[#128BDA] dark:border-[#128BDA]",
                              bg: "bg-[#E8F4FC] dark:bg-[#0d2a3d]",
                              badge: "bg-[#128BDA] text-white",
                            },
                            ai: {
                              label: "AI",
                              border: "border-l-2 border-[#FF832B] dark:border-[#FF832B]",
                              bg: "bg-[#FFF3EA] dark:bg-[#3d2314]",
                              badge: "bg-[#FF832B] text-white",
                            },
                            user: {
                              label: "User",
                              border: "border-l-2 border-gray-300 dark:border-gray-600",
                              bg: "bg-muted/30 dark:bg-muted/10",
                              badge: "bg-gray-500 text-white",
                            }
                          }

                          // Primary role drives the bubble border/bg colour
                          const primaryStyle = roleStyles[resolvedRoles[0]] || roleStyles.user
                          const bubbleClass = `rounded px-2.5 py-2 ${primaryStyle.border} ${primaryStyle.bg}`
                          const authorName = c.author_name || "User"
                          const dateStr = new Date(c.created_at).toLocaleString("en-US", { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

                          return (
                            <div key={c.id || i} className={bubbleClass}>
                              <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                                <span className="font-bold text-foreground">{authorName}</span>
                                <span>•</span>
                                {resolvedRoles.map((role) => {
                                  const s = roleStyles[role] || roleStyles.user
                                  return (
                                    <span key={role} className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${s.badge}`}>
                                      {s.label}
                                    </span>
                                  )
                                })}
                                <span>•</span>
                                <span>{dateStr}</span>
                              </div>
                              <div className="mt-1 text-[11px] leading-snug text-foreground whitespace-pre-wrap">{c.content}</div>
                            </div>
                          )
                        })
                      )}
                    </div>

                    {isResolved ? (
                      <div className="text-[11px] italic text-muted-foreground border-t border-foreground/10 pt-2">
                        Discussion closed — flag {normalizedStatus}.
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 border-t border-foreground/10 pt-2">
                        <input
                          type="text"
                          placeholder="Write a message…"
                          value={commentInput[findingKey] || ""}
                          onChange={(e) => setCommentInput(prev => ({ ...prev, [findingKey]: e.target.value }))}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              handlePostComment(findingKey);
                            }
                          }}
                          className="h-8 flex-1 rounded-md border border-foreground/15 bg-background px-2.5 text-[11px] outline-none placeholder:text-muted-foreground focus:border-[#5BC0EB] focus:ring-1 focus:ring-[#5BC0EB]"
                        />
                        <button
                          type="button"
                          disabled={!commentInput[findingKey]?.trim() || isKeyLoading(`comment-${findingKey}`)}
                          onClick={() => handlePostComment(findingKey)}
                          className="h-8 shrink-0 rounded-md bg-[#D97A1F] px-3 text-[11px] font-semibold text-white hover:bg-[#D97A1F]/90 disabled:opacity-50"
                        >
                          {isKeyLoading(`comment-${findingKey}`) ? "..." : "Post"}
                        </button>
                      </div>
                    )}
                  </div>

                  {(() => {
                    if (isResolved) {
                      // Accepted this session but still needs a suggestion — show pending banner
                      if (needsSuggestionPick) {
                        return (
                          <div className="mt-4 rounded-xl border border-dashed border-amber-300 bg-amber-50/70 px-4 py-3 text-[12px] font-semibold text-amber-700 dark:border-amber-700/50 dark:bg-amber-950/30 dark:text-amber-400">
                            ⚠ Select a suggestion above to complete acceptance before approving.
                          </div>
                        )
                      }
                      return (
                        <div className="mt-4 pt-4 border-t border-foreground/10 flex items-center gap-2.5 text-[13.5px] font-semibold">
                          {normalizedStatus === "accepted" ? (
                            <>
                              <Check className="h-5 w-5 text-green-600 dark:text-green-500" strokeWidth={2.5} />
                              <span className="text-green-600 dark:text-green-500">Accepted by compliance</span>
                            </>
                          ) : normalizedStatus === "rejected" ? (
                            <>
                              <X className="h-5 w-5 text-red-600 dark:text-red-500" strokeWidth={2.5} />
                              <span className="text-red-600 dark:text-red-500">Rejected</span>
                            </>
                          ) : (
                            <>
                              <Ban className="h-5 w-5 text-gray-500 dark:text-gray-400" strokeWidth={2.5} />
                              <span className="text-gray-500 dark:text-gray-400">Dismissed</span>
                            </>
                          )}
                        </div>
                      )
                    }

                    if (!(showMarketingButtons || showComplianceButtons)) return null

                    const cardLoadingKeys = Array.from(new Set([findingKey, ...groupIds, f.id]))
                    const isCardLoading = isKeyLoading(cardLoadingKeys)

                    return (
                    <div className="mt-4 flex flex-col gap-3">
                      {showComplianceButtons && (
                         <div className="grid grid-cols-2 gap-2.5">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                if (!hasMarketingAlt) {
                                  // When Marketing suggested alternative is not present, directly open confirmation modal
                                  setAcceptAltConfirm({
                                    findingId: findingKey,
                                    choice: "ai",
                                    isGroup: groupItems.length > 0,
                                    groupIds: groupIds
                                  })
                                } else {
                                  // Step 1: Accept the flag
                                  if (groupItems.length > 0) {
                                    void handleAcceptMany(groupIds)
                                  } else {
                                    void handleAccept(findingKey, groupIds)
                                  }
                                  // Step 2: Marketing suggestion is present, so let user pick between AI and Marketing suggestion
                                  setPendingSuggestionIds((prev) => new Set(prev).add(findingKey))
                                }
                              }}
                              disabled={isCardLoading}
                              className={cn(
                                "flex items-center justify-center gap-2 rounded-xl border px-2 py-2.5 text-sm font-semibold transition-colors",
                                isCardLoading 
                                  ? "border-green-200/50 bg-green-500/50 text-white/90 opacity-50 cursor-not-allowed" 
                                  : "border-green-500 bg-green-500 text-white hover:bg-green-600 hover:border-green-600"
                              )}
                              style={{ fontFamily: "Inter, sans-serif" }}
                            >
                              <Check className="h-4 w-4 shrink-0" strokeWidth={2.5} />
                              <span>{isCardLoading ? "Accepting..." : "Accept"}</span>
                            </button>

                            <button
                                type="button"
                                onClick={(e) => {
                                  e.preventDefault()
                                  e.stopPropagation()
                                  setSelectedAltChoice((prev) => {
                                    const next = { ...prev }
                                    delete next[findingKey]
                                    return next
                                  })
                                  setRejectModalFindingId(findingKey)
                                  setRejectModalGroupIds(groupIds)
                                }}
                                disabled={isCardLoading}
                                className={cn(
                                  "flex items-center justify-center gap-2 rounded-xl border px-2 py-2.5 text-sm font-semibold transition-colors",
                                  isCardLoading 
                                    ? "border-foreground/15 bg-card text-red-600 opacity-50 cursor-not-allowed" 
                                    : "border-foreground/15 bg-card text-red-600 hover:bg-muted"
                                )}
                                style={{ fontFamily: "Inter, sans-serif" }}
                              >
                                <X className="h-4 w-4 shrink-0" strokeWidth={2.5} />
                                <span>Reject</span>
                              </button>
                         </div>
                      )}
                    </div>
                    )
                  })()}
              </div>
              </>
              ) : null}
            </div>
          )
      })}
      </div>

      <div className="mt-auto flex shrink-0 items-center justify-between gap-3 pt-4">
        <div className="text-[11px] text-muted-foreground">Rate AI Analysis</div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setRating((v) => (v === "like" ? null : "like"))}
            className={cn(
              "inline-flex h-9 items-center gap-2 rounded-lg px-4 text-xs font-semibold",
              rating === "like"
                ? "bg-[#4169E1] text-white hover:bg-[#4169E1]/90"
                : "border border-foreground/15 bg-card text-foreground hover:bg-accent"
            )}
          >
            <ThumbsUp className="h-4 w-4" />
            Like
          </button>
          <button
            type="button"
            onClick={() => setDislikeFeedbackOpen(true)}
            className={cn(
              "inline-flex h-9 items-center gap-2 rounded-lg px-4 text-xs font-semibold",
              rating === "dislike"
                ? "bg-foreground/10 text-foreground"
                : "border border-foreground/15 bg-card text-foreground hover:bg-accent"
            )}
          >
            <ThumbsDown className="h-4 w-4" />
            Dislike
          </button>
        </div>
      </div>

      {/* ── Dismiss Modal ── */}
      {dismissModalFindingId && typeof document !== "undefined"
        ? createPortal(
            <div
              className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
              role="dialog"
              aria-modal="true"
              onMouseDown={(e) => {
                if (e.target === e.currentTarget) {
                  setDismissModalFindingId(null)
                  setDismissModalGroupIds([])
                  setDismissReason("")
                  setDismissOtherNote("")
                }
              }}
            >
              <div className="w-[min(480px,calc(100vw-32px))] rounded-xl bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                <div className="flex items-start justify-between gap-4 px-6 pt-6">
                  <div className="flex items-center gap-3">
                    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-red-100 dark:bg-red-900/30">
                      <Ban className="h-5 w-5 text-red-600 dark:text-red-400" />
                    </div>
                    <div>
                      <div className="text-base font-semibold text-foreground">
                        Dismiss this claim?
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        This marks the flag as a false positive and closes it. The original text stands unchanged, and the discussion is locked.
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setDismissModalFindingId(null)
                      setDismissModalGroupIds([])
                      setDismissReason("")
                      setDismissOtherNote("")
                    }}
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <div className="px-6 pb-6 pt-5">
                  <div className="mb-6 space-y-3">
                    <div className="text-[13px] font-semibold text-foreground">Reason for dismissal:</div>
                    <div className="grid grid-cols-1 gap-2.5 max-h-[220px] overflow-y-auto pr-2 activity-scroll">
                      {[
                        "False Positive",
                        "Context Not Considered",
                        "Rule Misclassification",
                        "Evidence Available",
                        "Disclosure Provided Elsewhere",
                        "Firm-Approved Standard Wording",
                        "Business Override",
                        "Duplicate Flag",
                        "Other"
                      ].map((option) => (
                        <label key={option} className="flex items-start gap-2.5 cursor-pointer">
                          <input
                            type="checkbox"
                            name="dismiss_reason"
                            value={option}
                            checked={dismissReason === option}
                            onChange={() => setDismissReason(option)}
                            className="mt-0.5 h-3.5 w-3.5 shrink-0 cursor-pointer rounded border-foreground/30 text-red-600 focus:ring-red-600 dark:border-white/20 dark:bg-white/5"
                          />
                          <span className="text-[13px] leading-tight text-foreground/90">{option}</span>
                        </label>
                      ))}
                    </div>

                    {dismissReason === "Other" && (
                      <div className="mt-3 pl-6">
                        <textarea
                          placeholder="Please provide a mandatory comment..."
                          value={dismissOtherNote}
                          onChange={(e) => setDismissOtherNote(e.target.value)}
                          className="min-h-[60px] w-full resize-y rounded-md border border-foreground/15 bg-background px-3 py-2 text-[13px] outline-none placeholder:text-muted-foreground focus:border-red-500 focus:ring-1 focus:ring-red-500"
                        />
                      </div>
                    )}
                  </div>
                  <div className="mt-5 flex justify-end gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        setDismissModalFindingId(null)
                        setDismissModalGroupIds([])
                        setDismissReason("")
                        setDismissOtherNote("")
                      }}
                      className="h-9 rounded-lg border border-foreground/15 bg-card px-5 text-xs font-medium text-foreground hover:bg-accent"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (dismissModalGroupIds.length > 0) {
                          void handleDismissMany(dismissModalGroupIds)
                        } else if (dismissModalFindingId) {
                          void handleDismissMany([dismissModalFindingId])
                        }
                      }}
                      disabled={isKeyLoading([dismissModalFindingId || "", ...dismissModalGroupIds]) || !dismissReason || (dismissReason === "Other" && !dismissOtherNote.trim())}
                      className="h-9 rounded-lg bg-red-600 px-5 text-xs font-semibold text-white hover:bg-red-600/90 disabled:opacity-50"
                    >
                      {isKeyLoading([dismissModalFindingId || "", ...dismissModalGroupIds]) ? "Dismissing..." : "Dismiss claim"}
                    </button>
                  </div>
                </div>
              </div>
            </div>,
            document.body
          )
        : null}

      {/* ── Accept Alternative Modal ── */}
      {acceptAltConfirm && typeof document !== "undefined"
        ? createPortal(
            <div className="relative z-[9999]">
              <div 
                className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
                onClick={() => setAcceptAltConfirm(null)}
              >
                <div 
                  className="w-[min(400px,calc(100vw-32px))] rounded-xl bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-start justify-between gap-4 px-6 pt-6">
                    <div className="flex items-center gap-3">
                      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-green-100 dark:bg-green-900/30">
                        <Check className="h-5 w-5 text-green-600 dark:text-green-400" />
                      </div>
                      <div>
                        <div className="text-base font-semibold text-foreground">
                          Accept Suggestion?
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          Are you sure you want to accept this {acceptAltConfirm.choice === "ai" ? "AI" : "Marketing"} suggestion? This action cannot be undone.
                        </div>
                      </div>
                    </div>
                  </div>
                  
                  <div className="px-6 pb-6 pt-5 mt-2 flex justify-end gap-3">
                    <button
                      type="button"
                      onClick={() => setAcceptAltConfirm(null)}
                      className="h-9 rounded-lg border border-foreground/15 bg-card px-5 text-xs font-medium text-foreground hover:bg-accent"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        const targetId = acceptAltConfirm.findingId
                        const choice = acceptAltConfirm.choice
                        const isGroup = acceptAltConfirm.isGroup
                        const groupIds = acceptAltConfirm.groupIds
                        const mktId = acceptAltConfirm.marketingSuggestionId
                        setAcceptAltConfirm(null)
                        void handleAcceptThis(targetId, choice, isGroup, groupIds, mktId)
                      }}
                      disabled={isKeyLoading([acceptAltConfirm.findingId, ...(acceptAltConfirm.groupIds || [])])}
                      className="h-9 rounded-lg bg-green-600 px-5 text-xs font-semibold text-white hover:bg-green-600/90 disabled:opacity-50"
                    >
                      {isKeyLoading([acceptAltConfirm.findingId, ...(acceptAltConfirm.groupIds || [])]) ? "Accepting..." : "Accept"}
                    </button>
                  </div>
                </div>
              </div>
            </div>,
            document.body
          )
        : null}

      {/* ── Reject Modal ── */}
      {rejectModalFindingId && typeof document !== "undefined"
        ? createPortal(
            <div className="relative z-[9999]">
              <div 
                className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
                onClick={() => {
                  setRejectModalFindingId(null)
                  setRejectModalGroupIds([])
                  setRejectReason("")
                }}
              >
                <div 
                  className="w-[min(480px,calc(100vw-32px))] rounded-xl bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-start justify-between gap-4 px-6 pt-6">
                    <div className="flex items-center gap-3">
                      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-red-100 dark:bg-red-900/30">
                        <X className="h-5 w-5 text-red-600 dark:text-red-400" />
                      </div>
                      <div>
                        <div className="text-base font-semibold text-foreground">
                          Reject AI Suggestion?
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          Please provide a reason why this suggestion was rejected.
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setRejectModalFindingId(null)
                        setRejectModalGroupIds([])
                        setRejectReason("")
                      }}
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  
                  <div className="px-6 pb-6 pt-5">
                    <div className="mb-6 space-y-3">
                      <div className="text-[13px] font-semibold text-foreground">Reason for rejection:</div>
                      <div className="mt-3">
                        <textarea
                          placeholder="Why is this suggestion not helpful?"
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                          className="min-h-[80px] w-full resize-y rounded-md border border-foreground/15 bg-background px-3 py-2 text-[13px] outline-none placeholder:text-muted-foreground focus:border-red-500 focus:ring-1 focus:ring-red-500"
                        />
                      </div>
                    </div>

                    <div className="mt-5 flex justify-end gap-3">
                      <button
                        type="button"
                        onClick={() => {
                          setRejectModalFindingId(null)
                          setRejectModalGroupIds([])
                          setRejectReason("")
                        }}
                        className="h-9 rounded-lg border border-foreground/15 bg-card px-5 text-xs font-medium text-foreground hover:bg-accent"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (rejectModalGroupIds.length > 0) {
                            void handleRejectMany(rejectModalGroupIds, rejectReason)
                          } else if (rejectModalFindingId) {
                            void handleRejectMany([rejectModalFindingId], rejectReason)
                          }
                          setRejectModalFindingId(null)
                          setRejectModalGroupIds([])
                          setRejectReason("")
                        }}
                        disabled={isKeyLoading([rejectModalFindingId || "", ...rejectModalGroupIds]) || !rejectReason.trim()}
                        className="h-9 rounded-lg bg-red-600 px-5 text-xs font-semibold text-white hover:bg-red-600/90 disabled:opacity-50"
                      >
                        {isKeyLoading([rejectModalFindingId || "", ...rejectModalGroupIds]) ? "Rejecting..." : "Reject suggestion"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>,
            document.body
          )
        : null}


      <AddAlternativeSuggestionModal
        open={!!addAlternativeFinding}
        onClose={() => setAddAlternativeFinding(null)}
        currentAiSuggestion={addAlternativeFinding?.suggestedAlternative ?? ""}
        onSubmit={handleAddSuggestion}
      />

      <AddCommentModal
        open={!!addCommentFinding}
        onClose={() => setAddCommentFinding(null)}
        onSubmit={handleAddComment}
        orgSlug={orgSlug}
        findingId={addCommentFinding?.primaryFindingId || addCommentFinding?.id}
      />

      <DislikeFeedbackModal
        open={dislikeFeedbackOpen}
        onClose={() => setDislikeFeedbackOpen(false)}
        onSubmit={() => {
          setRating("dislike")
          // TODO: submit dislike feedback when API is available
        }}
      />
    </div>
  )
}
