import * as React from "react"
import { createPortal } from "react-dom"
import { Navigate, useNavigate, useParams } from "react-router-dom"
import { AlertTriangle, Maximize2 } from "lucide-react"
import { MainLayout } from "@/components/layout/MainLayout"
import { CommentTrail, type MentionUser } from "@/components/layout/comment-trail"
import { CommonHeaderCard } from "@/components/layout/common-header-card"
import { type DocumentStatus } from "@/components/layout/document-preview-card"
import { DocumentRightPanel } from "@/components/layout/document-right-panel"
import { AiComplianceAnalysis, type AiComplianceFinding } from "@/components/layout/ai-compliance-analysis"
import { ScanningInProgress } from "@/components/layout/scanning-in-progress"
import { documentsApi, workflowsApi, usersApi, reviewsApi, auditApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { UserSearchSelect } from "@/components/ui/user-search-select"

type PreviewCacheEntry = {
  expiresAt: number
  data: {
    url: string
    file_name: string
    mime: string
    original_url?: string
    preview_fallback?: boolean
  }
}

const PREVIEW_CACHE_TTL_MS = 55 * 60 * 1000
const previewUrlCache = new Map<string, PreviewCacheEntry>()

function readPreviewCache(cacheKey: string) {
  const hit = previewUrlCache.get(cacheKey)
  if (!hit) return null
  if (Date.now() > hit.expiresAt) {
    previewUrlCache.delete(cacheKey)
    return null
  }
  return hit.data
}

function writePreviewCache(cacheKey: string, data: PreviewCacheEntry["data"]) {
  previewUrlCache.set(cacheKey, {
    data,
    expiresAt: Date.now() + PREVIEW_CACHE_TTL_MS,
  })
}

/** Stages where AI analysis column + data should stay available (incl. after compliance reject / needs revision). */
const WORKFLOW_STAGES_WITH_AI_ANALYSIS: readonly string[] = [
  "marketing_review",
  "needs_revision",
  "compliance_review",
  "approved",
  "published",
  "rejected",
]

function workflowStageShowsAiAnalysis(stage: string | undefined | null): boolean {
  const s = (stage || "").trim()
  return WORKFLOW_STAGES_WITH_AI_ANALYSIS.includes(s)
}

type AiProgressPhase =
  | "parsing_document"
  | "classifying_document"
  | "analysing_document"
  | "performing_ai_analysis"
  | "consolidating_result"
  | "completed"
  | "failed"
  | "not_started"
  | "classification_done"
  | "processing"
  | "skipped"

function computeAiStageProgress(phase: AiProgressPhase, checked: number, total: number): number {
  const safeTotal = Math.max(1, total)
  const safeChecked = Math.max(0, Math.min(checked, safeTotal))
  if (phase === "processing" || phase === "not_started") return 15
  if (phase === "parsing_document") return 15
  if (phase === "classifying_document" || phase === "classification_done") return 30
  if (phase === "analysing_document") return 30
  if (phase === "performing_ai_analysis") return 30 + (safeChecked / safeTotal) * 50
  if (phase === "consolidating_result") return 85
  if (phase === "completed") return 100
  if (phase === "failed") return 0
  return 15
}

// ── Main page ─────────────────────────────────────────────────────
export default function DocumentDetailPage() {
  const { orgSlug, docId } = useParams<{ orgSlug: string; docId: string }>()
  const navigate = useNavigate()

  if (!orgSlug?.trim() || !docId?.trim()) {
    return <Navigate to="/pending-access" replace />
  }

  // ── Tab & layout state (matching reference design) ──
  const [activeTab, setActiveTab] = React.useState<"preview" | "trail">("preview")
  const [docStatus, setDocStatus] = React.useState<DocumentStatus>("in-review")
  const [rightPanelCollapsed, setRightPanelCollapsed] = React.useState(false)
  const [middlePanelCollapsed, setMiddlePanelCollapsed] = React.useState(false)
  const [claimed, setClaimed] = React.useState(false)
  /** The user ID of whoever currently holds this document for review (if any). */
  const [assignedToUserId, setAssignedToUserId] = React.useState<string | null>(null)
  const [analysisOpen, setAnalysisOpen] = React.useState(false)

  // ── Data state ──
  const [loading, setLoading] = React.useState(true)
  const [docData, setDocData] = React.useState<Record<string, any> | null>(null)
  const [review, setReview] = React.useState<Record<string, any> | null>(null)
  const [workflowSteps, setWorkflowSteps] = React.useState<Record<string, any>[]>([])
  const [aiFindings, setAiFindings] = React.useState<AiComplianceFinding[]>([])
  const [comments, setComments] = React.useState<Record<string, any>[]>([])
  const [mentionUsers, setMentionUsers] = React.useState<MentionUser[]>([])
  const [aiAnalysisCompleted, setAiAnalysisCompleted] = React.useState(false)
  const [aiAnalysisError, setAiAnalysisError] = React.useState<string | null>(null)
  const [aiAnalysisState, setAiAnalysisState] = React.useState<
    "processing" | "completed" | "failed" | "not_started" | "unknown" | undefined
  >(undefined)
  const [aiAnalysisPhase, setAiAnalysisPhase] = React.useState<AiProgressPhase>("not_started")
  const [aiRulesChecked, setAiRulesChecked] = React.useState(0)
  const [aiRulesTotal, setAiRulesTotal] = React.useState(1)
  const [documentFileUrl, setDocumentFileUrl] = React.useState<string | null>(null)
  const [documentFileName, setDocumentFileName] = React.useState<string | null>(null)
  const [documentFileMime, setDocumentFileMime] = React.useState<string | null>(null)
  const [documentOriginalUrl, setDocumentOriginalUrl] = React.useState<string | null>(null)
  const [documentPreviewFallback, setDocumentPreviewFallback] = React.useState(false)
  /** Avoid re-fetching presigned S3 URLs on every poll (new URL string reloads the preview iframe). */
  const documentFileVersionRef = React.useRef<string | null>(null)
  const classificationDoneRef = React.useRef(false)
  const [isClassificationPending, setIsClassificationPending] = React.useState(false)
  /** Blob URL of the annotated (highlighted) PDF — replaces the raw S3 URL after analysis completes. */
  const [annotatedFileUrl, setAnnotatedFileUrl] = React.useState<string | null>(null)
  const [annotatedFileName, setAnnotatedFileName] = React.useState<string | null>(null)
  const [annotatedFileMime, setAnnotatedFileMime] = React.useState<string | null>(null)
  const [annotatedOriginalUrl, setAnnotatedOriginalUrl] = React.useState<string | null>(null)
  const [annotatedPreviewFallback, setAnnotatedPreviewFallback] = React.useState(false)
  const annotatedFileDocRef = React.useRef<string | null>(null)
  const [userRoles, setUserRoles] = React.useState<string[]>([])
  /** Same as `userRoles` but updated synchronously so `refreshData` (e.g. right after getUserInfo) sees SME before first paint. */
  const userRolesRef = React.useRef<string[]>([])
  React.useLayoutEffect(() => {
    userRolesRef.current = userRoles
  }, [userRoles])
  const [currentUserId, setCurrentUserId] = React.useState<string | null>(null)
  /** Same as `currentUserId` but updated synchronously so `refreshData` sees the user ID before first paint. */
  const currentUserIdRef = React.useRef<string | null>(null)
  const [currentUserEmail, setCurrentUserEmail] = React.useState<string | null>(null)
  const [actionLoading, setActionLoading] = React.useState(false)
  const [actionError, setActionError] = React.useState<string | null>(null)
  const [aiAnalysisProgress, setAiAnalysisProgress] = React.useState(0)
  const [aiAnalysisStartTime, setAiAnalysisStartTime] = React.useState<number | null>(null)
  const [aiRetryLoading, setAiRetryLoading] = React.useState(false)
  const [selectedPreviewPage, setSelectedPreviewPage] = React.useState<number | null>(null)
  const [selectedPreviewLine, setSelectedPreviewLine] = React.useState<number | null>(null)
  const [previewJumpNonce, setPreviewJumpNonce] = React.useState(0)
  const [previewIframeLoading, setPreviewIframeLoading] = React.useState(false)
  const [versions, setVersions] = React.useState<any[]>([])
  const [currentVersionId, setCurrentVersionId] = React.useState<string | undefined>(undefined)
  const previewContainerRef = React.useRef<HTMLDivElement>(null)
  /** Incremented each time an SSE event fires so child components can re-fetch their own data. */
  const [findingsRefreshTick, setFindingsRefreshTick] = React.useState(0)
  /** True while a user-initiated flag action (accept/reject/dismiss) is in flight and has
   *  already called refreshData(). The SSE handler checks this to avoid a duplicate reload. */
  const localActionPendingRef = React.useRef(false)

  // ── Modal state ──
  const [rejectOpen, setRejectOpen] = React.useState(false)
  const [rejectStep, setRejectStep] = React.useState<"form" | "success">("form")
  const [rejectReason, setRejectReason] = React.useState("")
  const [requestChangesOpen, setRequestChangesOpen] = React.useState(false)
  const [requestChangesStep, setRequestChangesStep] = React.useState<"form" | "success">("form")
  const [requestChangesReason, setRequestChangesReason] = React.useState("")

  // ── Marketing / Compliance Approve modals ──
  const [marketingApproveOpen, setMarketingApproveOpen] = React.useState(false)
  const [complianceReviewerId, setComplianceReviewerId] = React.useState("")
  const [complianceReviewers, setComplianceReviewers] = React.useState<Record<string, any>[]>([])
  const [smeApproveOpen, setSmeApproveOpen] = React.useState(false)
  const [complianceApproveOpen, setComplianceApproveOpen] = React.useState(false)
  /** Count of compliance flags that are accepted but still need a suggestion selected. Gates the Approve button. */
  const [pendingSuggestions, setPendingSuggestions] = React.useState(0)

  // ── Tab change handler ──
  const handleTabChange = React.useCallback((tab: "preview" | "trail") => {
    setActiveTab(tab)
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: "smooth" })
    })
  }, [])

  const withPageFragment = React.useCallback((url: string | null, page: number | null, _line?: number | null, nonce?: number) => {
    if (!url) return ""
    const noHash = url.split("#")[0]
    if (!page || page < 1) {
      return `${noHash}#toolbar=1`
    }
    // Use strict page jump with FitH, which is more reliably honored by embedded PDF viewers.
    return `${noHash}#page=${page}&view=FitH&toolbar=1&nav=${nonce ?? 0}`
  }, [])

  const getPreviewIframeSource = React.useCallback(
    (
      url: string | null,
      fileName: string | null,
      mime: string | null,
      page: number | null,
      line?: number | null,
      nonce?: number
    ) => {
      if (!url) return ""

      const safeName = (fileName || "").toLowerCase()
      const safeMime = (mime || "").toLowerCase()

      const isPdf = safeName.endsWith(".pdf") || safeMime.includes("pdf")
      return isPdf ? withPageFragment(url, page, line, nonce) : url
    },
    [withPageFragment]
  )

  const applyDocumentPreviewState = React.useCallback((fileData: {
    url: string
    file_name: string
    mime: string
    original_url?: string
    preview_fallback?: boolean
  }) => {
    setDocumentFileUrl(fileData.url)
    setDocumentFileName(fileData.file_name || null)
    setDocumentFileMime(fileData.mime || null)
    setDocumentOriginalUrl(fileData.original_url || fileData.url || null)
    setDocumentPreviewFallback(Boolean(fileData.preview_fallback))
  }, [])

  const applyAnnotatedPreviewState = React.useCallback((fileData: {
    url: string
    file_name: string
    mime: string
    original_url?: string
    preview_fallback?: boolean
  }) => {
    setAnnotatedFileUrl(fileData.url)
    setAnnotatedFileName(fileData.file_name || null)
    setAnnotatedFileMime(fileData.mime || null)
    setAnnotatedOriginalUrl(fileData.original_url || fileData.url || null)
    setAnnotatedPreviewFallback(Boolean(fileData.preview_fallback))
  }, [])

  // ── Data fetching ──
  const refreshData = React.useCallback(async () => {
    if (!docId) return
    const r = userRolesRef.current
    const viewerIsSmeOnly =
      r.includes("sme") &&
      !r.includes("marketing") &&
      !r.includes("compliance") &&
      !r.includes("super_admin")
    // Backend only allows marketing and compliance to fetch the annotated (highlighted) PDF
    const canFetchAnnotated = r.includes("marketing") || r.includes("compliance")
    try {
      if (viewerIsSmeOnly) {
        setAnnotatedFileUrl(null)
        setAnnotatedFileName(null)
        setAnnotatedFileMime(null)
        setAnnotatedOriginalUrl(null)
        setAnnotatedPreviewFallback(false)
        annotatedFileDocRef.current = null
      }
      setAiAnalysisError(null)
      const reviewPromise = documentsApi.getReview(orgSlug, docId).catch((error) => {
        const message = error instanceof Error ? error.message : "AI analysis data is unavailable."
        console.error("Failed to fetch document review / AI analysis:", error)
        setAiAnalysisError(message)
        return null
      })

      const [doc, reviewData] = await Promise.all([
        documentsApi.get(orgSlug, docId),
        reviewPromise,
      ])
      setDocData(doc)
      setReview(reviewData)

      // Only mark as claimed for the current user if they are the assigned reviewer.
      // Other users with the same role should NOT see action buttons when a specific
      // reviewer has been assigned — they are observers, not the active reviewer.
      const assignedTo = doc.assigned_to ? String(doc.assigned_to) : null
      const viewerIsAssigned =
        assignedTo != null &&
        currentUserIdRef.current != null &&
        assignedTo === String(currentUserIdRef.current)
      setClaimed(viewerIsAssigned)
      setAssignedToUserId(assignedTo)

      const docStatus = (doc.status || "").toLowerCase()
      const stageForClassification = doc.workflow_stage || "sme_review"

      // review_id = content_reviews.id; workflow references it via workflows.review_id
      const reviewId = reviewData?.id || reviewData?.review_id
      let latestWorkflowSteps: any[] = []
      if (reviewId) {
        try {
          const [workflowStepsData, commentsData, versionData] = await Promise.all([
            documentsApi.getDocumentWorkflowSteps(orgSlug, docId),
            documentsApi.getDocumentComments(orgSlug, docId),
            auditApi.getReviewVersions(orgSlug, reviewId).catch(() => ({ versions: [] }))
          ])
          latestWorkflowSteps = workflowStepsData || []
          setWorkflowSteps(latestWorkflowSteps)
          setComments(commentsData || [])
          setVersions(versionData.versions || [])
          
          if (doc.current_version_id && !currentVersionId) {
            setCurrentVersionId(String(doc.current_version_id))
          }
        } catch (e) {
          console.error("Failed to fetch workflow/comments/versions:", e)
        }
      }

      const reviewIdForClassification =
        reviewId || (doc.review_id != null ? String(doc.review_id) : null)

      if (
        stageForClassification !== "sme_review" ||
        docStatus === "skipped" ||
        !reviewIdForClassification
      ) {
        classificationDoneRef.current = true
        setIsClassificationPending(false)
      } else if (classificationDoneRef.current) {
        setIsClassificationPending(false)
      } else if (docStatus !== "processing") {
        classificationDoneRef.current = true
        setIsClassificationPending(false)
      } else {
        let classificationDone = false
        try {
          const audit = await documentsApi.getDocumentUnifiedAuditTrail(orgSlug, docId)
          classificationDone = (audit?.events ?? []).some(
            (e: Record<string, unknown>) => e.event_type === "ai_classification_completed"
          )
        } catch {
          classificationDone = false
        }
        classificationDoneRef.current = classificationDone
        setIsClassificationPending(!classificationDone)
      }

      const stage = doc.workflow_stage || "sme_review"
      const localIsMarketingStage = stage === "marketing_review" || stage === "needs_revision"
      const lastWorkflowAction = latestWorkflowSteps[latestWorkflowSteps.length - 1]?.action
      const isNeedsRevision =
        stage === "needs_revision" ||
        (localIsMarketingStage &&
          (lastWorkflowAction === "request_changes" || lastWorkflowAction === "needs_revision"))
      // If it's marketing stage but needs revision, set status accordingly
      if (stage === "rejected") setDocStatus("rejected")
      else if (isNeedsRevision) setDocStatus("rejected")
      else if (["marketing_review", "compliance_review", "approved"].includes(stage))
        setDocStatus("in-review")
      else setDocStatus("in-review")

      // Handle AI findings:
      // - Backend now returns `ai_analysis_state` to disambiguate "processing" vs "completed with 0 findings"
      // - We only show "No compliance findings detected" when analysis_state is completed (or unknown fallback logic)
      const stageForAnalysis = doc.workflow_stage || ""
      const shouldShowAnalysis = workflowStageShowsAiAnalysis(stageForAnalysis)
      const versionId = doc.current_version_id != null ? String(doc.current_version_id) : null

      const aiState = (reviewData as any)?.ai_analysis_state as
        | "processing"
        | "completed"
        | "failed"
        | "not_started"
        | "unknown"
        | undefined
      const aiPhase = ((reviewData as any)?.ai_analysis_phase ||
        (aiState === "completed"
          ? "completed"
          : aiState === "failed"
            ? "failed"
            : aiState === "processing"
              ? "parsing_document"
              : "not_started")) as
        | "parsing_document"
        | "classifying_document"
        | "analysing_document"
        | "performing_ai_analysis"
        | "consolidating_result"
        | "completed"
        | "failed"
        | "not_started"
      const rulesChecked = Math.max(0, Number((reviewData as any)?.ai_rules_checked ?? 0))
      const rulesTotal = Math.max(1, Number((reviewData as any)?.ai_rules_total ?? 1))

      // Store AI analysis state for use in progress animation.
      // Force phase to match terminal states so the UI never shows a
      // stale intermediate phase (e.g. "consolidating_result" when completed).
      const resolvedPhase =
        aiState === "completed" ? "completed"
          : aiState === "failed" ? "failed"
            : aiPhase
      setAiAnalysisState(aiState)
      setAiAnalysisPhase(resolvedPhase)
      setAiRulesChecked(rulesChecked)
      setAiRulesTotal(rulesTotal)

      // Store the real server-side start time for accurate progress
      const serverStartedAt = (reviewData as any)?.ai_started_at
      if (serverStartedAt && aiState === "processing") {
        setAiAnalysisStartTime(new Date(serverStartedAt).getTime())
      }

      if (shouldShowAnalysis && aiState === "processing") {
        // Show progress UI until backend signals completion
        setAiFindings([])
        setAiAnalysisCompleted(false)
        setAnalysisOpen(prev => viewerIsSmeOnly ? false : true)
        const pollPhase: AiProgressPhase =
          resolvedPhase === "processing" || resolvedPhase === "not_started"
            ? "parsing_document"
            : (resolvedPhase as AiProgressPhase)
        setAiAnalysisProgress((prev) =>
          Math.max(prev, computeAiStageProgress(pollPhase, rulesChecked, rulesTotal))
        )
      } else if (shouldShowAnalysis && aiState === "failed") {
        setAiFindings([])
        setAiAnalysisCompleted(false)
        setAiAnalysisProgress(0)
        setAiAnalysisStartTime(null)
        setAnnotatedFileUrl(null)
        annotatedFileDocRef.current = null
        setAnalysisOpen(prev => viewerIsSmeOnly ? false : true)
      } else if (aiState === "completed" && Array.isArray(reviewData?.ai_findings)) {
        // Analysis completed — only trust findings when backend says completed (not not_started + empty [])

        // ── Group by canonical claim hash, then claim_id, then text fallback ──────
        // canonical_claim_hash is backend-owned and stable across model/provider drift.
        // claim_id remains a secondary key; text slice is a final fallback.
        const findingsByClaim = new Map<string, Array<Record<string, any>>>()

        ;(reviewData.ai_findings as Array<Record<string, any>>).forEach((f) => {
          const canonicalHash = String(f.canonical_claim_hash || "").trim()
          const claimId = String(f.claim_id || "").trim()
          const fallbackKey = canonicalHash
            ? `h:${canonicalHash}`
            : claimId
            ? `cid:${claimId}`
            : `txt:${String(f.claim_text || f.title || f.id || "").trim().slice(0, 200)}`

          if (!findingsByClaim.has(fallbackKey)) findingsByClaim.set(fallbackKey, [])
          findingsByClaim.get(fallbackKey)!.push(f)
        })

        const findings: AiComplianceFinding[] = []

        const toRuleLabel = (f: Record<string, any>) =>
          f.rule_code && f.rule_name
            ? `Rule ${String(f.rule_code).replace("RULE-", "")} - ${f.rule_name}`
            : f.rule_name || (f.rule_code ? `Rule ${String(f.rule_code).replace("RULE-", "")}` : "Rule")

        // Process grouped findings (one card per claim, but keep per-item status)
        // Also assign a group-level findingCode (1..N) so the code matches the grouped cards.
        let claimGroupIndex = 0
        findingsByClaim.forEach((claimFindings, _) => {
          claimGroupIndex += 1
          const firstFinding = claimFindings[0]
          const rules = claimFindings.map(toRuleLabel)

          const severities = claimFindings.map((f) => String(f.risk_level || "LOW").toUpperCase())
          const severityOrder = { HIGH: 3, MEDIUM: 2, LOW: 1 }
          const highestSeverity = severities.reduce(
            (a, b) =>
              severityOrder[a as keyof typeof severityOrder] > severityOrder[b as keyof typeof severityOrder] ? a : b,
            "LOW"
          )

          const items = claimFindings.map((f) => ({
            id: String(f.id || ""),
            label: toRuleLabel(f),
            status: String(f.status || "pending").trim().toLowerCase(),
          })).filter((it) => !!it.id)

          // Aggregate status for the grouped claim card.
          // Business rule: if ANY underlying finding is accepted, show the whole claim as accepted.
          // Otherwise if any is rejected, show rejected. Else pending.
          const statuses = items.map((it) => it.status)
          const groupStatus = statuses.includes("accepted")
            ? "accepted"
            : statuses.includes("rejected")
              ? "rejected"
              : statuses.includes("dismissed")
                ? "dismissed"
                : "pending"

          const acceptedSuggestionId =
            groupStatus === "accepted"
              ? (claimFindings.find((f) => f.accepted_suggestion_id)?.accepted_suggestion_id as
                  | string
                  | null
                  | undefined) ?? null
              : null

          const canonicalHash = String(firstFinding.canonical_claim_hash || "").trim()
          const cid = String(firstFinding.claim_id || "").trim()
          const fCodes = Array.from(new Set(claimFindings.map((f) => f.finding_code).filter(Boolean))).map(String)
          const cardId =
            canonicalHash
              ? `claim-hash-${canonicalHash}`
              : cid
              ? `claim-${cid}`
              : (firstFinding.id || `group-${claimGroupIndex}`)
          findings.push({
            id: cardId,
            primaryFindingId: items[0]?.id || undefined,
            severity: (highestSeverity.charAt(0).toUpperCase() + highestSeverity.slice(1).toLowerCase()) as
              | "High"
              | "Medium"
              | "Low",
            title: firstFinding.title || "Compliance Finding",
            summary: firstFinding.description || firstFinding.why_risky || "",
            rule: rules[0] || "Rule",
            rules: rules.length > 1 ? rules : undefined,
            groupItems: items.length > 1 ? items : undefined,
            claimText: firstFinding.claim_text || undefined,
            whyRisky: firstFinding.why_risky || undefined,
            ruleRationale: firstFinding.rationale || undefined,
            suggestedAlternative: firstFinding.ai_suggestion || undefined,
            status: groupStatus,
            acceptedSuggestionId,
            location: firstFinding.location || undefined,
            findingCode: firstFinding.finding_code || String(claimGroupIndex),
            findingCodes: fCodes.length > 0 ? fCodes : [String(claimGroupIndex)],
          })
        })


        setAiFindings(findings)
        // At this point we have a stable findings array from backend; treat as completed
        setAiAnalysisCompleted(true)
        setAiAnalysisProgress(100)
        setAiAnalysisStartTime(null)
        if (shouldShowAnalysis && !viewerIsSmeOnly) setAnalysisOpen(true)

        // Fetch annotated (highlighted) PDF once per doc — SME-only users cannot access `/annotated_file` (403); use `/file` only.
        if (canFetchAnnotated && docId && annotatedFileDocRef.current !== docId) {
          annotatedFileDocRef.current = docId
          const annotatedCacheKey = `annotated:${docId}:${versionId || "none"}`
          const cachedAnnotated = readPreviewCache(annotatedCacheKey)
          if (cachedAnnotated) {
            applyAnnotatedPreviewState(cachedAnnotated)
          } else {
            documentsApi.getAnnotatedFile(orgSlug, docId)
            .then((fileData) => {
              applyAnnotatedPreviewState(fileData)
              writePreviewCache(annotatedCacheKey, fileData)
            })
            .catch((err) => {
              console.warn("Annotated PDF fetch failed, using raw file:", err)
              setAnnotatedFileUrl(null)
              setAnnotatedFileName(null)
              setAnnotatedFileMime(null)
              setAnnotatedOriginalUrl(null)
              setAnnotatedPreviewFallback(false)
              annotatedFileDocRef.current = null
            })
          }
        }
      } else if (shouldShowAnalysis && (aiState === "completed" || aiState === "not_started" || aiState === "unknown")) {
        // Completed but findings payload shape edge cases, or not started / unknown — not actively processing
        if (aiState === "completed") {
          setAiFindings([])
          setAiAnalysisCompleted(true)
          setAiAnalysisProgress(100)
          setAiAnalysisStartTime(null)
        } else {
          setAiFindings([])
          setAiAnalysisCompleted(false)
          setAiAnalysisProgress(0)
          setAiAnalysisStartTime(null)
          setAnnotatedFileUrl(null)
          setAnnotatedFileName(null)
          setAnnotatedFileMime(null)
          setAnnotatedOriginalUrl(null)
          setAnnotatedPreviewFallback(false)
          annotatedFileDocRef.current = null
        }
        if (!viewerIsSmeOnly) setAnalysisOpen(true)
      } else if (shouldShowAnalysis) {
        // Fallback when ai_analysis_state is missing — treat as idle, not "scanning"
        setAiFindings([])
        setAiAnalysisCompleted(false)
        setAiAnalysisProgress(0)
        setAiAnalysisStartTime(null)
        setAnnotatedFileUrl(null)
        setAnnotatedFileName(null)
        setAnnotatedFileMime(null)
        setAnnotatedOriginalUrl(null)
        setAnnotatedPreviewFallback(false)
        annotatedFileDocRef.current = null
        if (!viewerIsSmeOnly) setAnalysisOpen(true)
      } else {
        // Not in a stage that should show analysis
        setAiFindings([])
        setAiAnalysisCompleted(false)
        setAnnotatedFileUrl(null)
        setAnnotatedFileName(null)
        setAnnotatedFileMime(null)
        setAnnotatedOriginalUrl(null)
        setAnnotatedPreviewFallback(false)
        annotatedFileDocRef.current = null
      }

      // Presigned URLs change on every API call; only fetch when the stored file version changes
      // (e.g. after reupload) so AI polling does not reload the document preview every few seconds.
      const preferAnnotated =
        shouldShowAnalysis && aiState === "completed" && canFetchAnnotated
      const needsNewFile =
        versionId != null
          ? documentFileVersionRef.current !== versionId
          : documentFileVersionRef.current === null
      if (needsNewFile && !preferAnnotated) {
        const documentCacheKey = `version:${versionId || "none"}`
        const cachedPreview = readPreviewCache(documentCacheKey)
        if (cachedPreview) {
          applyDocumentPreviewState(cachedPreview)
          documentFileVersionRef.current = versionId ?? "__no_version__"
          return
        }
        try {
          const fileData = await documentsApi.getFile(orgSlug, docId)
          applyDocumentPreviewState(fileData)
          writePreviewCache(documentCacheKey, fileData)
          documentFileVersionRef.current = versionId ?? "__no_version__"
        } catch (e) {
          console.error("Failed to fetch file:", e)
        }
      }
      return doc
    } catch (error) {
      console.error("Failed to fetch document:", error)
      return null
    }
  }, [docId, orgSlug, applyAnnotatedPreviewState, applyDocumentPreviewState])

  /**
   * Called by AiComplianceAnalysis after a flag action completes.
   * Sets localActionPendingRef so the concurrent SSE event doesn't trigger
   * a second refreshData() call for the same action.
   */
  const handleFindingUpdate = React.useCallback(async () => {
    localActionPendingRef.current = true
    try {
      await refreshData()
    } finally {
      localActionPendingRef.current = false
    }
  }, [refreshData])

  const handleRetryAiAnalysis = React.useCallback(async () => {
    if (!docId) return
    setAiRetryLoading(true)
    try {
      await documentsApi.triggerAiAnalysis(orgSlug, docId)
      setAiAnalysisState("processing")
      setAiAnalysisPhase("parsing_document")
      setAiRulesChecked(0)
      setAiRulesTotal(1)
      setAiAnalysisCompleted(false)
      setAiAnalysisProgress(15)
      setAiAnalysisStartTime(Date.now())
      await refreshData()
    } catch (err: unknown) {
      console.error("Retry AI analysis failed:", err)
      setActionError(err instanceof Error ? err.message : "Could not restart analysis.")
    } finally {
      setAiRetryLoading(false)
    }
  }, [docId, refreshData])

  React.useEffect(() => {
    documentFileVersionRef.current = null
    classificationDoneRef.current = false
    setIsClassificationPending(false)
    setDocumentFileUrl(null)
    setDocumentFileName(null)
    setDocumentFileMime(null)
    setDocumentOriginalUrl(null)
    setDocumentPreviewFallback(false)
    setAnnotatedFileUrl(null)
    setAnnotatedFileName(null)
    setAnnotatedFileMime(null)
    setAnnotatedOriginalUrl(null)
    setAnnotatedPreviewFallback(false)
    annotatedFileDocRef.current = null
    setSelectedPreviewPage(null)
    setSelectedPreviewLine(null)
  }, [docId])

  React.useEffect(() => {
    const init = async () => {
      setLoading(true)
      try {
        const userInfo = (await documentsApi.getUserInfo().catch(() => null)) as Record<string, unknown> | null
        const rolesFromMe = Array.isArray(userInfo?.roles) ? (userInfo!.roles as string[]) : []
        if (rolesFromMe.length) setUserRoles(rolesFromMe)
        userRolesRef.current = rolesFromMe
        if (userInfo?.id != null) {
          const uid = String(userInfo.id)
          setCurrentUserId(uid)
          currentUserIdRef.current = uid
        } else {
          setCurrentUserId(null)
          currentUserIdRef.current = null
        }
        if (userInfo?.email != null && String(userInfo.email).trim()) {
          setCurrentUserEmail(String(userInfo.email).trim().toLowerCase())
        } else {
          setCurrentUserEmail(null)
        }
      } catch (e) {
        console.error("Failed to fetch user info:", e)
      }
      await refreshData()
      setLoading(false)
    }
    init()
  }, [docId, refreshData])

  const computeStageProgress = React.useCallback(
    (phase: AiProgressPhase, checked: number, total: number) =>
      computeAiStageProgress(phase, checked, total),
    []
  )

  // Unified SSE progress channel with auto-reconnect + single polling fallback.
  React.useEffect(() => {
    let eventSource: EventSource | null = null
    let pollInterval: number | undefined
    let reconnectTimer: number | undefined
    let cancelled = false
    let reconnectDelay = 2000

    const stageForAnalysis = docData?.workflow_stage || ""
    const shouldShowAnalysis = workflowStageShowsAiAnalysis(stageForAnalysis)
    const currentUserIsSme = userRoles.includes("sme")
    const isScanningActive = (aiAnalysisState === "processing" || aiAnalysisState === "not_started" || aiAnalysisState === "unknown") && !aiAnalysisCompleted

    const handleSseMessage = (ev: MessageEvent) => {
      if (cancelled) return
      try {
        const data = JSON.parse(ev.data)
        const phase = data.phase as AiProgressPhase
        const checked = Number(data.rules_checked ?? 0)
        const total = Math.max(1, Number(data.rules_total ?? 1))
        
        // Auto-transition UI from "not_started" to "processing" once a progress event is received
        if (phase && phase !== "completed" && phase !== "failed" && phase !== "classification_done") {
          setAiAnalysisState("processing")
        }
        
        setAiAnalysisPhase(phase)
        setAiRulesChecked(checked)
        setAiRulesTotal(total)
        const prog = computeStageProgress(phase, checked, total)
        setAiAnalysisProgress((prev) => Math.max(prev, prog))
        reconnectDelay = 2000
        
        // If classification completes and document is in scope, do NOT mark as completed yet (compliance scanning begins now).
        // If it is classified as out of scope, it is skipped/completed immediately.
        const isOutOfScopeDone = phase === "classification_done" && data.is_in_scope === false

        if (phase === "classification_done") {
          classificationDoneRef.current = true
          setIsClassificationPending(false)
          refreshData().then((doc) => {
             if (doc && doc.workflow_stage === "sme_review") {
                setAiAnalysisState("not_started")
                setAiAnalysisPhase("not_started")
                setAiAnalysisProgress(0)
             }
          })
        }
        
        if (phase === "completed" || isOutOfScopeDone) {
          setAiAnalysisProgress(100)
          setAiAnalysisCompleted(true)
          setAiAnalysisState("completed")
          refreshData()
        } else if (phase === "failed") {
          setAiAnalysisState("failed")
          refreshData()
        }
      } catch { /* ignore parse errors */ }
    }

    const stopPolling = () => {
      if (pollInterval) { window.clearInterval(pollInterval); pollInterval = undefined }
    }

    const startPolling = (intervalMs = 4000) => {
      stopPolling()
      pollInterval = window.setInterval(() => refreshData(), intervalMs)
    }

    const connectSse = () => {
      if (cancelled || !docId) return
      const sseUrl = documentsApi.analysisStreamUrl(orgSlug, docId)
      try {
        // withCredentials lets the browser send the httpOnly session cookie.
        eventSource = new EventSource(sseUrl, { withCredentials: true })
        eventSource.onmessage = handleSseMessage
        // Keep polling as backup: onopen alone does not mean events are flowing (nginx/proxy/redis).
        eventSource.onopen = () => { reconnectDelay = 2000 }
        eventSource.onerror = () => {
          eventSource?.close()
          eventSource = null
          if (cancelled) return
          startPolling()
          reconnectDelay = Math.min(reconnectDelay * 2, 30000)
          reconnectTimer = window.setTimeout(connectSse, reconnectDelay)
        }
      } catch {
        startPolling()
      }
    }

    const needsClassificationStream =
      (docData?.workflow_stage || "") === "sme_review" &&
      (docData?.status || "").toLowerCase() === "processing" &&
      !classificationDoneRef.current

    if (
      (shouldShowAnalysis && isScanningActive && !currentUserIsSme) ||
      needsClassificationStream
    ) {
      if (shouldShowAnalysis && isScanningActive && !currentUserIsSme) {
        setAnalysisOpen(true)
      }
      startPolling(4000)
      connectSse()
    } else if (!shouldShowAnalysis || aiAnalysisState === "not_started" || aiAnalysisState === "unknown") {
      if (!shouldShowAnalysis) setAnalysisOpen(false)
      if (aiAnalysisState === "not_started" || aiAnalysisState === "unknown") {
        setAiAnalysisStartTime(null)
        setAiAnalysisProgress(0)
      }
    } else if (aiAnalysisCompleted || aiAnalysisState === "completed") {
      setAiAnalysisProgress(100)
      setAiAnalysisStartTime(null)
    } else if (aiAnalysisState === "failed") {
      setAiAnalysisProgress(0)
      setAiAnalysisStartTime(null)
    }

    return () => {
      cancelled = true
      eventSource?.close()
      stopPolling()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
  }, [
    aiAnalysisCompleted,
    aiAnalysisState,
    computeStageProgress,
    docData?.workflow_stage,
    docData?.status,
    userRoles,
    refreshData,
    docId,
    orgSlug,
  ])

  // Fetch compliance reviewers when marketing approve modal opens
  React.useEffect(() => {
    if (marketingApproveOpen && complianceReviewers.length === 0) {
      usersApi.list("compliance").then(setComplianceReviewers).catch(() => {})
    }
  }, [marketingApproveOpen, complianceReviewers.length])

  // ── Derived state ──
  const isNonEducationalSkipped = (docData?.status || "").toLowerCase() === "skipped"
  const workflowStage = docData?.workflow_stage || "sme_review"
  const isSmeStage = workflowStage === "sme_review"
  const isMarketingStage = workflowStage === "marketing_review" || workflowStage === "needs_revision"
  const isComplianceStage = workflowStage === "compliance_review"
  const isApprovedStage = workflowStage === "approved"
  const isPublished = workflowStage === "published"
  const isRejected = workflowStage === "rejected"

  const isSmeUser = userRoles.includes("sme")
  const isMarketingUser = userRoles.includes("marketing")
  const isComplianceUser = userRoles.includes("compliance")
  const isSuperAdmin = userRoles.includes("super_admin")

  // A user is treated as an SME ONLY if they have the sme role and are
  // NOT also a marketing/compliance/super_admin user on this document's stage.
  // This prevents multi-role real accounts from being incorrectly blocked.
  // isSmeOnly: true if the user has ONLY the SME role in the system.
  const isSmeOnly = isSmeUser && !isMarketingUser && !isComplianceUser && !isSuperAdmin

  // isNeedsRevision must be defined BEFORE showAiAnalysis
  const latestWorkflowStep = workflowSteps[workflowSteps.length - 1]
  const lastWorkflowAction = latestWorkflowStep?.action
  const isNeedsRevision =
    workflowStage === "needs_revision" ||
    (isMarketingStage &&
      (lastWorkflowAction === "request_changes" || lastWorkflowAction === "needs_revision"))
  const isSmeRequestedChanges =
    isMarketingStage &&
    lastWorkflowAction === "request_changes" &&
    latestWorkflowStep?.previous_stage === "sme_review"
  const isComplianceRequestedChanges =
    isMarketingStage &&
    lastWorkflowAction === "request_changes" &&
    latestWorkflowStep?.previous_stage === "compliance_review"
  const isSmeRejectedToMarketing =
    isRejected &&
    lastWorkflowAction === "reject" &&
    latestWorkflowStep?.previous_stage === "sme_review"
  const canUploadNewVersion =
    Boolean(docId) &&
    isMarketingUser &&
    (workflowStage === "needs_revision" ||
      lastWorkflowAction === "request_changes" ||
      lastWorkflowAction === "needs_revision")

  // AI analysis visible after SME approval (and through reject / needs revision); hidden for SME users
  const showAiAnalysis =
    !isSmeRequestedChanges &&
    !isSmeRejectedToMarketing &&
    !isSmeUser &&
    !isNonEducationalSkipped &&
    !!docData?.workflow_stage &&
    workflowStageShowsAiAnalysis(docData.workflow_stage)

  const showBothHeaderTabs = !isNonEducationalSkipped

  // Open the AI analysis column whenever the stage allows it (incl. rejected / needs revision with completed runs)
  // SME users never see the AI analysis panel regardless of stage
  React.useEffect(() => {
    if (showAiAnalysis && !isSmeUser) {
      setAnalysisOpen(true)
    } else if (isSmeUser) {
      setAnalysisOpen(false)
    }
  }, [showAiAnalysis, isSmeUser])

  // Publish only for the original uploader (backend assigns approved docs to submitted_by) AND must be a marketing user.
  const canPublishDocument =
    isMarketingUser &&
    isApprovedStage &&
    currentUserId != null &&
    docData?.submitted_by != null &&
    String(currentUserId) === String(docData.submitted_by)

  // Can the current user act on the current stage?
  const canActOnCurrentStage =
    !isRejected &&
    !isPublished &&
    ((isSmeStage && isSmeUser) ||
      (isMarketingStage && isMarketingUser) ||
      (isComplianceStage && isComplianceUser) ||
      canPublishDocument)

  // Keep approve path available in marketing_review even after repeated
  // compliance request_changes cycles, so reviewers can resubmit back to compliance.
  const hideApproveButton = isRejected || isSmeRequestedChanges || isSmeRejectedToMarketing


  // Does the current stage require claiming before acting?
  const needsClaiming = isSmeStage || isComplianceStage

  // True when the document is claimed by a different user (not the viewer).
  // In this case, same-role peers should NOT see the Claim button either.
  const isAssignedToSomeoneElse =
    assignedToUserId != null &&
    (currentUserId == null || assignedToUserId !== String(currentUserId))

  // CommonHeaderCard props — role-based action visibility
  const showClaimButton = canActOnCurrentStage && needsClaiming && !claimed && !isAssignedToSomeoneElse
  const isClaimDisabledByClassification = isSmeStage && showClaimButton && isClassificationPending
  const headerClaimed = canActOnCurrentStage && (!needsClaiming || claimed)
  const headerStatus: DocumentStatus = isPublished ? "approved" : docStatus

  // ── Action handlers ──
  const handleClaimReview = async () => {
    if (!docId || isClaimDisabledByClassification) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.claim(orgSlug, docId)
      setClaimed(true)
      await refreshData()
    } catch (error) {
      console.error("Failed to claim review:", error)
      setActionError("Failed to claim review. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handleSmeApprove = async () => {
    if (!docId) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.smeApprove(orgSlug, docId)
      setSmeApproveOpen(false)
      await refreshData()
    } catch (error) {
      console.error("Failed to approve:", error)
      setActionError("Failed to approve document. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handleSmeReject = async () => {
    if (!docId) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.smeReject(orgSlug, docId, rejectReason)
      setRejectStep("success")
      setTimeout(() => {
        setRejectOpen(false)
        setRejectStep("form")
        setRejectReason("")
      }, 1500)
      await refreshData()
    } catch (error) {
      console.error("Failed to reject:", error)
      setActionError("Failed to reject document. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handleSmeRequestChanges = async () => {
    if (!docId) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.smeRequestChanges(orgSlug, docId, requestChangesReason)
      setRequestChangesStep("success")
      setTimeout(() => {
        setRequestChangesOpen(false)
        setRequestChangesStep("form")
        setRequestChangesReason("")
      }, 1500)
      await refreshData()
    } catch (error) {
      console.error("Failed to request changes:", error)
      setActionError("Failed to request changes. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handleMarketingApprove = async () => {
    if (!docId) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.marketingApprove(orgSlug, docId, complianceReviewerId || undefined)
      setMarketingApproveOpen(false)
      setComplianceReviewerId("")
      await refreshData()
    } catch (error) {
      console.error("Failed to approve:", error)
      setActionError("Failed to approve document. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handleComplianceApprove = async () => {
    if (!docId) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.complianceApprove(orgSlug, docId, true)
      setComplianceApproveOpen(false)
      await refreshData()
    } catch (error) {
      console.error("Failed to approve:", error)
      setActionError("Failed to approve document. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handleComplianceReject = async () => {
    if (!docId) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.complianceReject(orgSlug, docId, rejectReason)
      setRejectStep("success")
      setTimeout(() => {
        setRejectOpen(false)
        setRejectStep("form")
        setRejectReason("")
      }, 1500)
      await refreshData()
    } catch (error) {
      console.error("Failed to reject:", error)
      setActionError("Failed to reject document. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handleComplianceRequestChanges = async () => {
    if (!docId) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.complianceRequestChanges(orgSlug, docId, requestChangesReason)
      setRequestChangesStep("success")
      setTimeout(() => {
        setRequestChangesOpen(false)
        setRequestChangesStep("form")
        setRequestChangesReason("")
      }, 1500)
      await refreshData()
    } catch (error) {
      console.error("Failed to request changes:", error)
      setActionError("Failed to request changes. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handlePublish = async () => {
    if (!docId) return
    try {
      setActionError(null)
      setActionLoading(true)
      await documentsApi.publish(orgSlug, docId)
      await refreshData()
    } catch (error) {
      console.error("Failed to publish:", error)
      setActionError("Failed to publish document. Please try again.")
    } finally {
      setActionLoading(false)
    }
  }

  const handleSendComment = async (text: string, mentionedUserIds?: string[]) => {
    const reviewId = review?.id || review?.review_id
    if (!reviewId) return
    let body = text
    if (currentUserEmail) {
      const esc = currentUserEmail.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      body = body.replace(new RegExp(`@${esc}\\b`, "gi"), "").replace(/\s{2,}/g, " ").trim()
    }
    const ids =
      mentionedUserIds?.filter((id) => !currentUserId || String(id) !== String(currentUserId)) ?? undefined
    if (!body.trim()) return
    try {
      setActionError(null)
      await reviewsApi.addComment(orgSlug, reviewId, body, ids?.length ? ids : undefined)
      await refreshData()
    } catch (error) {
      console.error("Failed to send comment:", error)
      setActionError("Failed to send comment. Please try again.")
    }
  }

  React.useEffect(() => {
    const reviewId = String(review?.id || review?.review_id || "")
    if (!reviewId) return

    let eventSource: EventSource | null = null
    let fallbackPollTimer: number | undefined
    let reconnectTimer: number | undefined
    let cancelled = false
    let reconnectDelay = 2000

    const stopFallbackPolling = () => {
      if (fallbackPollTimer) {
        window.clearInterval(fallbackPollTimer)
        fallbackPollTimer = undefined
      }
    }

    const startFallbackPolling = () => {
      stopFallbackPolling()
      fallbackPollTimer = window.setInterval(() => {
        void refreshData()
      }, 60000)
    }

    const connectCommentsStream = () => {
      if (cancelled) return

      try {
        eventSource = new EventSource(
          reviewsApi.commentsStreamUrl(orgSlug, reviewId),
          { withCredentials: true },
        )
        eventSource.onopen = () => {
          stopFallbackPolling()
          reconnectDelay = 2000
        }
        eventSource.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data)
            const findingOnlyEvents = [
              "finding_comment_added",
              "finding_suggestion_added",
              "finding_suggestion_edited",
            ]
            if (findingOnlyEvents.includes(data.event)) {
              // Only refresh findings panel — avoid a full page data reload
              setFindingsRefreshTick((t) => t + 1)
              return
            }
            if (data.event === "workflow_stage_changed") {
              // Full page data refresh — stage badge, action buttons, workflow trail all update
              void refreshData()
              return
            }

            // For other events (e.g. finding_status_updated, comment_created)
            // refresh everything so status badges, counts, etc. stay in sync.
            // Skip if a local action already triggered refreshData() for this exact update.
            if (data.event === "finding_status_updated" && localActionPendingRef.current) {
              // Local action already refreshed — just bump the findings tick for sub-components
              setFindingsRefreshTick((t) => t + 1)
              return
            }
            void refreshData()
            setFindingsRefreshTick((t) => t + 1)
          } catch {
            // Malformed / keepalive data — still trigger a findings refresh
            void refreshData()
            setFindingsRefreshTick((t) => t + 1)
          }
        }
        eventSource.onerror = () => {
          eventSource?.close()
          eventSource = null
          if (cancelled) return
          startFallbackPolling()
          reconnectDelay = Math.min(reconnectDelay * 2, 30000)
          reconnectTimer = window.setTimeout(connectCommentsStream, reconnectDelay)
        }
      } catch {
        startFallbackPolling()
      }
    }

    connectCommentsStream()

    return () => {
      cancelled = true
      eventSource?.close()
      stopFallbackPolling()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
  }, [review?.id, review?.review_id, refreshData])

  React.useEffect(() => {
    let cancelled = false

    // Fetch ALL active org users so anyone in the organization can be @mentioned
    // in a comment — not just those already involved in this document's workflow.
    usersApi
      .list()
      .then((rows) => {
        if (cancelled) return
        setMentionUsers(
          (rows || [])
            .filter((u: Record<string, unknown>) => u.status !== "inactive")
            .map((u: Record<string, unknown>) => ({
              id: String(u.id),
              email: String(u.email ?? ""),
              name: String(u.name ?? u.email ?? "User"),
            }))
            .filter((u: MentionUser) => u.email)
        )
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [docData?.id])

  const mentionUsersForPicker = React.useMemo(() => {
    if (!currentUserId) return mentionUsers
    return mentionUsers.filter((u) => String(u.id) !== String(currentUserId))
  }, [mentionUsers, currentUserId])

  // Route the CommonHeaderCard "Approve" action based on current stage
  const handleApprove = () => {
    if (isSmeStage) setSmeApproveOpen(true)
    else if (isMarketingStage) {
      // Open marketing approve modal instead of direct approve
      setMarketingApproveOpen(true)
    }
    else if (isComplianceStage) setComplianceApproveOpen(true)
    else if (isApprovedStage) handlePublish()
  }

  // Route reject based on stage
  const executeReject = () => {
    if (isSmeStage) handleSmeReject()
    else if (isComplianceStage) handleComplianceReject()
  }

  // Route request changes based on stage
  const executeRequestChanges = () => {
    if (isSmeStage) handleSmeRequestChanges()
    else if (isComplianceStage) handleComplianceRequestChanges()
  }

  const handleVersionChange = React.useCallback(async (versionId: string) => {
    setCurrentVersionId(versionId)
    try {
      const documentCacheKey = `version:${versionId}`
      const cachedVersionPreview = readPreviewCache(documentCacheKey)
      if (cachedVersionPreview) {
        applyDocumentPreviewState(cachedVersionPreview)
      } else {
        const fileData = await documentsApi.getVersionFileUrl(orgSlug, versionId)
        applyDocumentPreviewState(fileData)
        writePreviewCache(documentCacheKey, fileData)
      }
      
      const isCurrent = docData?.current_version_id && String(docData.current_version_id) === String(versionId)
      if (isCurrent) {
        if (isSmeOnly) {
          setAnnotatedFileUrl(null)
          setAnnotatedFileName(null)
          setAnnotatedFileMime(null)
          setAnnotatedOriginalUrl(null)
          setAnnotatedPreviewFallback(false)
        } else if (docId) {
          // Restore annotated file for current version if it was previously fetched
          const annotatedCacheKey = `annotated:${docId}:${versionId}`
          const cachedAnnotated = readPreviewCache(annotatedCacheKey)
          if (cachedAnnotated) {
            applyAnnotatedPreviewState(cachedAnnotated)
          } else {
            documentsApi.getAnnotatedFile(orgSlug, docId)
              .then((data) => {
                applyAnnotatedPreviewState(data)
                writePreviewCache(annotatedCacheKey, data)
              })
              .catch(() => {
                setAnnotatedFileUrl(null)
                setAnnotatedFileName(null)
                setAnnotatedFileMime(null)
                setAnnotatedOriginalUrl(null)
                setAnnotatedPreviewFallback(false)
              })
          }
        }
      } else {
        setAnnotatedFileUrl(null)
        setAnnotatedFileName(null)
        setAnnotatedFileMime(null)
        setAnnotatedOriginalUrl(null)
        setAnnotatedPreviewFallback(false)
      }
    } catch (e) {
      console.error("Failed to fetch version file URL:", e)
    }
  }, [docId, docData?.current_version_id, applyAnnotatedPreviewState, applyDocumentPreviewState, isSmeOnly, orgSlug])

  const activePreviewFallback = annotatedFileUrl ? annotatedPreviewFallback : documentPreviewFallback
  const activePreviewMime = (annotatedFileMime || documentFileMime || "").toLowerCase()
  const activePreviewName = (annotatedFileName || documentFileName || "").toLowerCase()
  const activePreviewIsPdf = activePreviewMime.includes("pdf") || activePreviewName.endsWith(".pdf")
  const previewSrc = getPreviewIframeSource(
    annotatedFileUrl || documentFileUrl || "",
    annotatedFileName || documentFileName,
    annotatedFileMime || documentFileMime,
    selectedPreviewPage,
    selectedPreviewLine,
    previewJumpNonce
  )

  React.useEffect(() => {
    if (previewSrc && !activePreviewFallback && activePreviewIsPdf) {
      setPreviewIframeLoading(true)
    } else {
      setPreviewIframeLoading(false)
    }
  }, [previewSrc, activePreviewFallback, activePreviewIsPdf])

  // ── Modal keyboard/scroll handling ──
  React.useEffect(() => {
    const anyModalOpen =
      rejectOpen || requestChangesOpen || marketingApproveOpen || complianceApproveOpen || smeApproveOpen
    if (!anyModalOpen) return

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      if (rejectOpen) {
        setRejectOpen(false)
        setRejectStep("form")
        setRejectReason("")
      } else if (requestChangesOpen) {
        setRequestChangesOpen(false)
        setRequestChangesStep("form")
        setRequestChangesReason("")
      } else if (marketingApproveOpen) {
        setMarketingApproveOpen(false)
        setComplianceReviewerId("")
      } else if (smeApproveOpen) {
        setSmeApproveOpen(false)
      } else if (complianceApproveOpen) {
        setComplianceApproveOpen(false)
      }
    }
    window.addEventListener("keydown", onKeyDown)

    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      document.body.style.overflow = prevOverflow
    }
  }, [rejectOpen, requestChangesOpen, marketingApproveOpen, complianceApproveOpen, smeApproveOpen])

  const closeRequestChanges = React.useCallback(() => {
    setRequestChangesOpen(false)
    setRequestChangesStep("form")
    setRequestChangesReason("")
  }, [])

  const closeReject = React.useCallback(() => {
    setRejectOpen(false)
    setRejectStep("form")
    setRejectReason("")
  }, [])

  const closeMarketingApprove = React.useCallback(() => {
    setMarketingApproveOpen(false)
    setComplianceReviewerId("")
  }, [])

  const closeSmeApprove = React.useCallback(() => {
    setSmeApproveOpen(false)
  }, [])

  const closeComplianceApprove = React.useCallback(() => {
    setComplianceApproveOpen(false)
  }, [])

  // ── Workflow groups for DocumentRightPanel ──
  const workflowGroups = React.useMemo(() => {
    if (!workflowSteps.length) return []
    const grouped: Record<string, any[]> = {}
    workflowSteps.forEach((step: Record<string, any>) => {
      const versionLabel = step.version_label || "1.0"
      if (!grouped[versionLabel]) grouped[versionLabel] = []
      const action = step.action || ""
      grouped[versionLabel].push({
        kind:
          action === "approve" ||
          action === "sme_approve" ||
          action === "approve_and_lock" ||
          action === "publish" ||
          action === "approve_final"
            ? ("success" as const)
            : action === "reject"
              ? ("danger" as const)
              : action === "request_changes" || action === "needs_revision"
                ? ("danger" as const)
                : action === "claim" || action === "claimed"
                  ? ("warning" as const)
                  : ("info" as const),
        title:
          action === "approve"
            ? step.previous_stage === "sme_review"
              ? "Sent to Marketing Reviewer"
              : step.previous_stage === "marketing_review"
                ? "Sent to Compliance"
                : "Approved"
            : action === "sme_approve"
              ? "Sent to Marketing Reviewer"
              : action === "approve_and_lock"
                ? "Approve & Lock"
                : action === "reject"
                  ? "Rejected"
                  : action === "request_changes"
                    ? "Change Requested"
                    : action === "claim" || action === "claimed"
                      ? "Claimed for Review"
                      : action === "uploaded"
                        ? "Document Uploaded"
                        : action === "reuploaded"
                          ? "Document Re-uploaded"
                          : action === "submit_to_compliance"
                            ? "Sent to Compliance"
                            : action === "submit_to_marketing"
                              ? "Sent to Marketing"
                              : action === "assigned"
                                ? "Reviewer Assigned"
                                : action === "publish"
                                  ? "Published"
                                  : action || "Action",
        stage: (() => {
          // Special handling: if action is uploaded/reuploaded, show "Document Upload" instead of stage name
          if (action === "uploaded" || action === "reuploaded") {
            return "Document Upload"
          }
          const displayStage = step.previous_stage || step.stage
          return displayStage === "sme_review"
            ? "SME Review"
            : displayStage === "marketing_review"
              ? "Marketing Review"
              : displayStage === "compliance_review"
                ? "Compliance Review"
                : displayStage === "needs_revision"
                  ? "Needs Revision"
                  : displayStage === "approved"
                    ? "Approved"
                    : displayStage === "published"
                      ? "Published"
                      : displayStage === "rejected"
                        ? "Rejected"
                        : displayStage || ""
        })(),
        user:
          step.user_name ||
          step.completed_by_name ||
          step.claimed_by_name ||
          "System",
        time: (() => {
          const iso = step.completed_at || step.claimed_at || step.created_at
          const utcIso = iso.endsWith("Z") ? iso : iso + "Z"
          const d = new Date(utcIso)
          return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} at ${d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true })}`
        })(),
        highlight:
          action === "approve" || action === "approve_and_lock" || action === "publish" || action === "approve_final"
            ? ("green" as const)
            : action === "reject" || action === "request_changes"
              ? ("orange" as const)
              : action === "claim" || action === "claimed"
                ? ("orange" as const)
                : undefined,
        comment: step.comment || undefined,
      })
    })
    return Object.entries(grouped).map(([versionLabel, items]) => ({ versionLabel, items }))
  }, [workflowSteps])

  // ── Comments for CommentTrail ──
  const mappedCommentGroups = React.useMemo(() => {
    if (!comments.length) return []
    const grouped: Record<string, any[]> = {}
    comments.forEach((c: Record<string, any>) => {
      const versionLabel = c.version_label || "1.0"
      if (!grouped[versionLabel]) grouped[versionLabel] = []
      
      const isSent = c.author_id === docData?.submitted_by || false // Simplify: mark as sent if marketing user or match ID
      const isOwnComment =
        currentUserId != null && String(c.author_id ?? "") === String(currentUserId)
      const roleTag = (() => {
        if (!c.author_role) return "@User"
        const roles = c.author_role.split(",").map((p: any) => p.trim().toLowerCase()).filter(Boolean)
        if (roles.length === 0) return "@User"
        const mapped = roles.map((r: string) => {
          if (r === "sme") return "SME"
          if (r === "marketing") return "Marketing"
          if (r === "compliance") return "Compliance"
          if (r === "super_admin" || r === "super admin") return "Super Admin"
          if (r === "ai" || r === "system") return "AI"
          if (r === "admin") return "Admin"
          if (r === "unknown") return "User"
          return r.replace(/\b\w/g, (c) => c.toUpperCase())
        })
        let unique = Array.from(new Set(mapped)).filter(Boolean)
        // Move super_admin to end so operational role appears first
        if (unique.includes("Super Admin") && unique.length > 1) {
          unique = [...unique.filter((u) => u !== "Super Admin"), "Super Admin"]
        }
        const finalRoles = unique.filter((u) => u !== "User" || unique.length === 1)
        if (finalRoles.length === 0) return "@User"
        return `@${finalRoles.join(", ")}`
      })()
      grouped[versionLabel].push({
        user: c.author_name || "User",
        tag: roleTag,
        text: c.content,
        time: (() => {
          const iso = c.created_at
          const utcIso = iso.endsWith("Z") ? iso : iso + "Z"
          const d = new Date(utcIso)
          return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} at ${d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true })}`
        })(),
        isSent,
      })
    })
    return Object.entries(grouped).map(([versionLabel, items]) => ({ versionLabel, items }))
  }, [comments, docData, currentUserId])

  // ── Header display logic (matching reference design) ──
  const headerDisplayTab: "preview" | "trail" = activeTab

  // All users can see both Preview and Workflow (Trail)
  const headerDisplayTabFinal: "preview" | "trail" = headerDisplayTab

  // Only allow request changes / reject for stages that support it (SME, Compliance)
  const supportsRejectAndChanges = isSmeStage || isComplianceStage

  // ── Loading / not found ──
  if (loading) {
    return (
      <MainLayout
        header={{
          breadcrumbs: [
            { label: "ComplyCore", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
            { label: "Validate Documents", to: `/orgs/${orgSlug}/validate-documents` },
            { label: "Details" },
          ],
        }}
      >
        <div className="flex items-center justify-center p-8">
          <div className="text-sm text-muted-foreground">
            Loading document...
          </div>
        </div>
      </MainLayout>
    )
  }

  if (!docData) {
    return (
      <MainLayout
        header={{
          breadcrumbs: [
            { label: "Dashboards", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
            { label: "Validate Documents", to: `/orgs/${orgSlug}/validate-documents` },
            { label: "Details" },
          ],
        }}
      >
        <div className="flex items-center justify-center p-8">
          <div className="text-sm text-muted-foreground">
            Document not found
          </div>
        </div>
      </MainLayout>
    )
  }

  // ── Status badge text ──
  const isFailedDoc = (docData?.status || "").toLowerCase() === "failed" || aiAnalysisState === "failed"
  const stageBadgeText = isFailedDoc
    ? "Failed"
    : isNonEducationalSkipped
      ? "Out of Scope"
      : isPublished
        ? "Published"
        : isRejected
          ? "Rejected"
          : workflowStage === "approved"
            ? "Approved"
            : isNeedsRevision
              ? "Needs Revision"
              : claimed
                ? "In Review"
                : workflowStage === "sme_review"
                  ? "SME Review"
                  : workflowStage === "marketing_review"
                    ? "Marketing Review"
                    : workflowStage === "compliance_review"
                    ? "Compliance Review"
                    : workflowStage

  const isMarketingSendToCompliance =
    isMarketingStage && (isMarketingUser || isSuperAdmin) && !hideApproveButton
  const isAiAnalysisReadyForCompliance =
    aiAnalysisState === "completed" && aiAnalysisCompleted
  const isApproveDisabledByAi =
    isMarketingSendToCompliance && !isAiAnalysisReadyForCompliance
  const isApproveDisabledByNonEducational = isMarketingStage && isNonEducationalSkipped
  const unresolvedFindings = aiFindings.filter((f) => {
    const status = String(f.status || "").trim().toLowerCase()
    return status !== "accepted" && status !== "rejected" && status !== "dismissed"
  })
  const isComplianceApproveDisabledByFindings = isComplianceStage && unresolvedFindings.length > 0
  const isComplianceApproveDisabledByPendingSuggestions = isComplianceStage && pendingSuggestions > 0
  const isApproveDisabled = isApproveDisabledByAi || isApproveDisabledByNonEducational || isComplianceApproveDisabledByFindings || isComplianceApproveDisabledByPendingSuggestions
  const approveDisabledTooltip = isApproveDisabledByAi
    ? aiAnalysisState === "failed"
      ? "AI compliance analysis failed. Retry analysis before sending to compliance."
      : aiAnalysisState === "not_started" || aiAnalysisState === "unknown"
        ? "AI compliance analysis has not completed yet. Please wait until it finishes."
        : "AI Compliance Analysis is in progress. Please wait until it completes."
    : isApproveDisabledByNonEducational
      ? "This document is classified as non-educational (out of scope) and cannot be sent to compliance."
      : isComplianceApproveDisabledByPendingSuggestions
        ? `${pendingSuggestions} flag(s) require a suggestion to be selected before approving.`
        : isComplianceApproveDisabledByFindings
          ? "Please resolve all findings before approving."
          : undefined
  const aiStageLabel =
    aiAnalysisPhase === "parsing_document"
      ? "Parsing Document"
      : aiAnalysisPhase === "classifying_document"
        ? "Extracting Text"
        : aiAnalysisPhase === "analysing_document"
          ? "Analysing Document"
          : aiAnalysisPhase === "performing_ai_analysis"
            ? "Performing AI Analysis"
            : aiAnalysisPhase === "consolidating_result"
              ? "Consolidating Result"
              : aiAnalysisPhase === "completed"
                ? "Analysis Complete"
                : aiAnalysisPhase === "failed"
                  ? "Analysis Failed"
                  : "Scanning in progress"
  const aiRulesProgressLabel =
    aiAnalysisPhase === "performing_ai_analysis"
      ? "Checking general compliance rules"
      : undefined
  const activeOriginalUrl = annotatedFileUrl ? annotatedOriginalUrl : documentOriginalUrl

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "Dashboards", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
          { label: "Validate Documents", to: `/orgs/${orgSlug}/validate-documents` },
          { label: "Details" },
        ],
      }}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        {/* ── Title + status badge ── */}
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-sm font-semibold text-foreground">
            {docData.name || "Document"}
          </h1>
            <span className={`inline-flex items-center gap-1 rounded border px-2.5 py-0.5 text-xs font-medium ${
              isNonEducationalSkipped
                ? "border-amber-500 bg-amber-500/5 text-amber-600 dark:text-amber-400"
                : "border-[#FF8D28] bg-[#FF8D28]/5 text-[#FF8D28]"
            }`}>
            {stageBadgeText}
            </span>
        </div>
        
        {actionError && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {actionError}
          </div>
        )}

        {isFailedDoc && (
          <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3.5 flex items-center gap-3 text-red-600 dark:text-red-400 shadow-sm animate-in fade-in slide-in-from-top-1 duration-200">
            <AlertTriangle className="h-5 w-5 flex-shrink-0" />
            <div>
              <h4 className="font-semibold text-sm">Document Analysis Failed</h4>
              <p className="text-xs opacity-90 mt-0.5">
                The document processing timed out or failed to complete. No AI compliance analysis, review actions, or audit records are available for this attempt.
              </p>
            </div>
          </div>
        )}

        {isNonEducationalSkipped && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3.5 flex items-center gap-3 text-amber-600 dark:text-amber-400 shadow-sm animate-in fade-in slide-in-from-top-1 duration-200">
            <AlertTriangle className="h-5 w-5 flex-shrink-0" />
            <div>
              <h4 className="font-semibold text-sm">Out of Scope Document</h4>
              <p className="text-xs opacity-90 mt-0.5">
                This document has been automatically classified as non-educational/out of scope by the AI compliance engine. No workflow, comments, or review actions are required or available.
              </p>
            </div>
          </div>
        )}

        {isSmeRequestedChanges && (isMarketingUser || isSuperAdmin) && (
          <div className="rounded-lg border border-[#FF8D28]/20 bg-[#FF8D28]/5 px-4 py-3.5 flex items-center gap-3 text-[#FF8D28] shadow-sm animate-in fade-in slide-in-from-top-1 duration-200">
            <AlertTriangle className="h-5 w-5 flex-shrink-0" />
            <div>
              <h4 className="font-semibold text-sm">SME requested changes</h4>
              <p className="text-xs opacity-90 mt-0.5">
                Upload a new version to address SME feedback and resubmit for SME review. AI compliance analysis will run after SME approves the revised document.
              </p>
            </div>
          </div>
        )}

        {isComplianceRequestedChanges && (isMarketingUser || isSuperAdmin) && (
          <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-3.5 flex items-center gap-3 text-blue-600 dark:text-blue-400 shadow-sm animate-in fade-in slide-in-from-top-1 duration-200">
            <AlertTriangle className="h-5 w-5 flex-shrink-0" />
            <div>
              <h4 className="font-semibold text-sm">Compliance requested changes</h4>
              <p className="text-xs opacity-90 mt-0.5">
                Upload a new version to address compliance feedback. The revised document will undergo AI compliance analysis in Marketing Review so you can review findings before manually sending it back to Compliance.
              </p>
            </div>
          </div>
        )}

        {isSmeRejectedToMarketing && (isMarketingUser || isSuperAdmin) && (
          <div className="rounded-lg border border-[#FF8D28]/20 bg-[#FF8D28]/5 px-4 py-3.5 flex items-center gap-3 text-[#FF8D28] shadow-sm animate-in fade-in slide-in-from-top-1 duration-200">
            <AlertTriangle className="h-5 w-5 flex-shrink-0" />
            <div>
              <h4 className="font-semibold text-sm">SME rejected this document</h4>
              <p className="text-xs opacity-90 mt-0.5">
                This document has been rejected. Please upload a new document to start a new review process.
              </p>
            </div>
          </div>
        )}



        {/* ── Tabs + actions card (CommonHeaderCard — same design as reference) ── */}

        <CommonHeaderCard
          activeTab={activeTab}
          onTabChange={handleTabChange}
          showBothTabs={showBothHeaderTabs}
          claimed={isNonEducationalSkipped ? false : headerClaimed}
          status={isNonEducationalSkipped ? "Out of Scope" : headerStatus}
          trailCount={comments.length}
          displayTab={headerDisplayTabFinal}
          className="relative"
          versions={versions}
          currentVersionId={currentVersionId}
          onVersionChange={handleVersionChange}
          onClaimReview={showClaimButton && !isNonEducationalSkipped ? handleClaimReview : undefined}
          isClaimDisabled={isClaimDisabledByClassification}
          claimDisabledTooltip="Document classification is in progress. Please wait until it completes."
          onApprove={!hideApproveButton && canActOnCurrentStage && !isNonEducationalSkipped ? handleApprove : undefined}
          approveButtonText={isApprovedStage ? "Publish" : (isMarketingStage ? "Send to Compliance Reviewer" : "Approve")}
          isApproveDisabled={isApproveDisabled}
          approveDisabledTooltip={approveDisabledTooltip}
          onRequestChanges={
            supportsRejectAndChanges && canActOnCurrentStage && !isNonEducationalSkipped
              ? () => {
            setRequestChangesStep("form")
            setRequestChangesOpen(true)
                }
              : undefined
          }
          onReject={
            supportsRejectAndChanges && canActOnCurrentStage && !isNonEducationalSkipped
              ? () => {
            setRejectStep("form")
            setRejectReason("")
            setRejectOpen(true)
                }
              : undefined
          }
          onUploadNewVersion={
            canUploadNewVersion && !isNonEducationalSkipped
              ? () =>
                  navigate(`/upload-document?reupload_id=${docId}`, {
                    state: { returnTo: `/orgs/${orgSlug}/validate-documents/detail/${docId}` },
                  })
              : undefined
          }
        />

        {/* ── Body layout ──
              States & ratios (same as reference):
              A) 2 cards, right expanded    → left 65 : right 35
              B) 2 cards, right collapsed   → left fills all, collapsed button strip
              C) 3 cards, right expanded    → left 35 : middle 30 : right 35
              D) 3 cards, right collapsed   → left 60 : middle 40
        ── */}
        {(() => {
          // For SME users, never show AI analysis middle panel
          const threePanel =
            analysisOpen &&
            showAiAnalysis &&
            activeTab === "preview"

          const fullWidthCommentView = activeTab === "trail"

          const leftFlex = isNonEducationalSkipped || fullWidthCommentView
            ? "flex-[100]"
            : threePanel
            ? middlePanelCollapsed
              ? rightPanelCollapsed
                ? "flex-[100]"
                : "flex-[65]"
              : rightPanelCollapsed
                ? "flex-[55]"
                : "flex-[33]"
            : "flex-[65]"

          const midFlex = rightPanelCollapsed ? "flex-[45]" : "flex-[33]"

          return (
            <div className="relative flex min-h-[100vh] flex-1 items-stretch gap-4">
              {/* ── LEFT ── */}
              <div className={`min-w-0 flex flex-col min-h-0 ${leftFlex}`}>
                {activeTab === "preview" ? (
                  documentFileUrl || annotatedFileUrl ? (
                    <div 
                      ref={previewContainerRef}
                      className="flex flex-col flex-1 min-h-0 rounded-xl bg-card border p-4"
                    >
                      {activePreviewFallback ? (
                        <div className="flex h-full min-h-[320px] items-center justify-center">
                          <a
                            href={activeOriginalUrl || annotatedFileUrl || documentFileUrl || ""}
                            target="_blank"
                            rel="noreferrer"
                            className="text-sm font-medium text-sky-600"
                          >
                            Open original file
                          </a>
                        </div>
                      ) : !activePreviewIsPdf ? (
                        <div className="flex h-full min-h-[320px] items-center justify-center">
                          <div className="flex flex-col items-center gap-2 text-center">
                            <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#128BDA]/20 border-t-[#128BDA]" />
                            <p className="text-sm font-medium text-foreground">Preparing PDF preview</p>
                            <p className="text-xs text-muted-foreground">Your file is being prepared for in-app viewing.</p>
                          </div>
                        </div>
                      ) : (
                        <div className="relative flex-1 min-h-0">
                          {previewIframeLoading ? (
                            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 rounded-md bg-card/95">
                              <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#128BDA]/20 border-t-[#128BDA]" />
                              <div className="space-y-1 text-center">
                                <p className="text-sm font-medium text-foreground">Loading document preview</p>
                                <p className="text-xs text-muted-foreground">Rendering pages and controls...</p>
                              </div>
                            </div>
                          ) : null}
                          <iframe
                            key={previewSrc}
                            src={previewSrc}
                            onLoad={() => setPreviewIframeLoading(false)}
                            onError={() => setPreviewIframeLoading(false)}
                            className="w-full flex-1 min-h-0 border-0"
                            title="Document Preview"
                            style={{ height: "100%" }}
                          />
                        </div>
                      )}
                    </div>
                  ) : isFailedDoc ? (
                    <div className="flex flex-1 items-center justify-center rounded-xl border border-red-500/20 bg-card p-6">
                      <div className="flex flex-col items-center gap-3 text-center">
                        <AlertTriangle className="h-8 w-8 text-red-500" />
                        <div>
                          <p className="text-sm font-semibold text-foreground">Document Analysis Failed</p>
                          <p className="text-xs text-muted-foreground mt-0.5">This document processing failed or timed out.</p>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-1 items-center justify-center rounded-xl border bg-card p-6">
                      <div className="flex flex-col items-center gap-3 text-center">
                        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#128BDA]/20 border-t-[#128BDA]" />
                        <div>
                          <p className="text-sm font-medium text-foreground">Preparing document preview</p>
                          <p className="text-xs text-muted-foreground">Fetching latest file from storage...</p>
                        </div>
                      </div>
                    </div>
                  )
                ) : (
                  <CommentTrail
                    className="flex-1 border-0"
                    commentThreadKey={docId || ""}
                    commentGroups={mappedCommentGroups}
                    mentionUsers={mentionUsersForPicker}
                    onSendComment={handleSendComment}
                    disabled={showClaimButton}
                    disabledMessage="Claim the review before adding comments"
                    showCollapseToggle={activeTab === "trail"}
                    onCollapseToggle={() => handleTabChange("preview")}
                  />
                )}
              </div>

              {/* ── MIDDLE: AI Compliance Analysis ── */}
              {threePanel && !middlePanelCollapsed ? (
                <div
                  className={`hidden min-w-0 flex-col ${midFlex} lg:flex`}
                >
                  <div className="flex h-full w-full flex-col overflow-hidden rounded-xl bg-card p-4">
                    {aiAnalysisError ? (
                      <div className="flex h-full flex-col items-center justify-center gap-4 px-4 text-center">
                        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-50 text-amber-600 ring-1 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-800">
                          <AlertTriangle className="h-5 w-5" />
                        </div>
                        <div>
                          <div className="text-xs font-semibold text-foreground">AI Compliance Analysis</div>
                          <p className="mt-2 text-xs text-muted-foreground">{aiAnalysisError}</p>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          className="rounded-md bg-[#128BDA] font-semibold text-white hover:bg-[#128BDA]/90"
                          onClick={() => void refreshData()}
                        >
                          Retry loading analysis
                        </Button>
                      </div>
                    ) : aiAnalysisCompleted ? (
                      // Analysis completed - show findings (even if empty)
                      aiFindings.length > 0 ? (
                    <AiComplianceAnalysis
                      orgSlug={orgSlug}
                      findings={aiFindings}
                      userRoles={userRoles}
                      workflowStage={workflowStage}
                      reviewId={review?.id || review?.review_id}
                      onFindingUpdate={handleFindingUpdate}
                      refreshTrigger={findingsRefreshTick}
                      isClaimed={claimed}
                      needsClaiming={needsClaiming}
                      onCollapseClick={() => setMiddlePanelCollapsed(true)}
                      onPendingSuggestionsChange={setPendingSuggestions}
                      onLocationClick={(page) => {
                        const targetPage = page.page
                        setActiveTab("preview")
                        setSelectedPreviewPage(targetPage)
                        setSelectedPreviewLine(null)
                        setPreviewJumpNonce((n) => n + 1)
                        // Wait a tiny bit for tab switch if needed and then scroll
                        setTimeout(() => {
                          previewContainerRef.current?.scrollIntoView({ 
                            behavior: "smooth", 
                            block: "start" 
                          })
                        }, 50)
                      }}
                    />
                      ) : (
                        <div className="flex flex-col items-center justify-center h-full text-center">
                          <div className="text-xs font-semibold text-foreground mb-3">AI Compliance Analysis</div>
                          <div className="text-xs text-muted-foreground">
                            No compliance findings detected.
                          </div>
                        </div>
                      )
                    ) : aiAnalysisState === "failed" ? (
                      <div className="flex h-full flex-col items-center justify-center gap-4 px-4 text-center">
                        <div>
                          <div className="text-xs font-semibold text-foreground">AI Compliance Analysis</div>
                          <p className="mt-2 text-xs text-muted-foreground">
                            Automated analysis stopped due to an error. You can retry to run it again.
                          </p>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          className="rounded-md bg-[#128BDA] font-semibold text-white hover:bg-[#128BDA]/90"
                          disabled={aiRetryLoading}
                          onClick={() => void handleRetryAiAnalysis()}
                        >
                          {aiRetryLoading ? "Starting…" : "Retry analysis"}
                        </Button>
                        <button
                          type="button"
                          className="text-xs text-muted-foreground underline hover:text-foreground"
                          onClick={() => setMiddlePanelCollapsed(true)}
                        >
                          Collapse panel
                        </button>
                      </div>
                    ) : aiAnalysisState === "processing" && !aiAnalysisCompleted ? (
                      <ScanningInProgress
                        progress={aiAnalysisProgress}
                        stageLabel={aiStageLabel}
                        rulesProgressLabel={aiRulesProgressLabel}
                        onCollapseClick={() => setMiddlePanelCollapsed(true)}
                      />
                    ) : (
                      <div className="flex min-h-0 flex-col">
                        <div className="flex items-center justify-between gap-3 pb-3">
                          <span className="text-sm font-semibold text-foreground">AI Compliance Analysis</span>
                          <button
                            type="button"
                            onClick={() => setMiddlePanelCollapsed(true)}
                            className="shrink-0"
                            aria-label="Collapse panel"
                          >
                            <img
                              src="/documents/collapsibleIcon.svg"
                              alt=""
                              className="h-6 w-6 dark:invert dark:opacity-90"
                              width={24}
                              height={24}
                            />
                          </button>
                        </div>
                        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 py-8 text-center">
                          <p className="text-xs text-muted-foreground">
                            {aiAnalysisState === "not_started"
                              ? "AI analysis is not running. It will start automatically when a run is queued for this document."
                              : aiAnalysisState === "unknown"
                                ? "Analysis status is unavailable. Try refreshing the page."
                                : "No analysis is running right now. Results will appear here when a run completes."}
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : null}

              {/* ── RIGHT: Approval Workflow + Comments ── */}
              {!rightPanelCollapsed && !fullWidthCommentView && !isNonEducationalSkipped ? (
                <div className="flex min-h-0 min-w-0 flex-[33] flex-col overflow-hidden">
                  <DocumentRightPanel
                    workflowGroups={workflowGroups}
                    commentThreadKey={docId || ""}
                    commentGroups={mappedCommentGroups}
                    commentCount={comments.length}
                    mentionUsers={mentionUsersForPicker}
                    showComments={true}
                    onApprovedClick={() =>
                      setDocStatus((s) =>
                        s === "approved" ? "in-review" : "approved"
                      )
                    }
                    onSendComment={handleSendComment}
                    disabled={false}
                    disabledMessage="Claim the review before adding comments"
                    commentsExpanded={activeTab === "trail"}
                    onCommentsExpandToggle={() =>
                      handleTabChange(activeTab === "trail" ? "preview" : "trail")
                    }
                    onCollapseClick={() => setRightPanelCollapsed(true)}
                    className="flex-1 border-0"
                  />
                </div>
              ) : null}

              {/* ── COLLAPSED PANELS (Stacked on Right Edge) ── */}
              {activeTab === "preview" && !isNonEducationalSkipped && ((threePanel && middlePanelCollapsed) || rightPanelCollapsed) && (
                <div className="flex w-12 shrink-0 flex-col gap-4 self-stretch">
                  {threePanel && middlePanelCollapsed && (
                    <button
                      type="button"
                      onClick={() => setMiddlePanelCollapsed(false)}
                      className="flex flex-1 flex-col items-center justify-start overflow-hidden rounded-xl border border-border bg-card py-4 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground shadow-sm"
                      aria-label="Expand AI Compliance Analysis"
                    >
                      <Maximize2 className="mb-4 h-4 w-4 shrink-0" strokeWidth={2} />
                      <span className="[writing-mode:vertical-rl] rotate-180 text-xs font-semibold tracking-wider whitespace-nowrap">
                        AI Compliance Analysis
                      </span>
                    </button>
                  )}
                  {rightPanelCollapsed && (
                    <button
                      type="button"
                      onClick={() => setRightPanelCollapsed(false)}
                      className="flex flex-1 flex-col items-center justify-start overflow-hidden rounded-xl border border-border bg-card py-4 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground shadow-sm"
                      aria-label="Expand sidebar"
                    >
                      <Maximize2 className="mb-4 h-4 w-4 shrink-0" strokeWidth={2} />
                      <span className="[writing-mode:vertical-rl] rotate-180 text-xs font-semibold tracking-wider whitespace-nowrap">
                        Approval Workflow
                      </span>
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })()}

        {/* ── Marketing Approve modal ── */}
        {marketingApproveOpen && typeof document !== "undefined"
          ? createPortal(
              <div
                className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
                role="dialog"
                aria-modal="true"
                aria-label="Approve and assign compliance reviewer"
                onMouseDown={(e) => {
                  if (e.target === e.currentTarget) closeMarketingApprove()
                }}
              >
                <div className="w-[min(480px,calc(100vw-32px))] rounded-xl bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                  <div className="flex items-start justify-between gap-4 px-6 pt-6">
                    <div>
                      <div className="text-base font-semibold text-foreground">
                        Approve Document
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Approve this document and send it to compliance review.
                        You can optionally assign a specific compliance reviewer.
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={closeMarketingApprove}
                      className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label="Close"
                    >
                      <span className="text-xl leading-none">×</span>
                    </button>
                  </div>

                  <div className="px-6 pb-6 pt-5">
                    <label className="text-sm font-semibold text-foreground">
                      Assign Compliance Reviewer (Optional)
                    </label>
                    <UserSearchSelect
                      role="compliance"
                      value={complianceReviewerId}
                      onChange={setComplianceReviewerId}
                      placeholder="Search compliance reviewers..."
                      defaultLabel="All compliance reviewers can claim"
                    />
                    <p className="mt-1 text-xs text-muted-foreground">
                      If not assigned, all compliance reviewers will see the &apos;Claim Review&apos; option.
                    </p>

                    <div className="mt-5 flex justify-end gap-3">
                      <button
                        type="button"
                        onClick={closeMarketingApprove}
                        className="h-9 rounded-lg border border-foreground/15 bg-card px-5 text-xs font-medium text-foreground hover:bg-accent"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={handleMarketingApprove}
                        disabled={actionLoading}
                        className="h-9 rounded-lg bg-emerald-600 px-5 text-xs font-semibold text-white hover:bg-emerald-600/90 disabled:opacity-50"
                      >
                        {actionLoading ? "Approving..." : "Approve & Send to Compliance"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>,
              document.body
            )
          : null}

        {/* ── Compliance Approve modal ── */}
        {complianceApproveOpen && typeof document !== "undefined"
          ? createPortal(
              <div
                className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
                role="dialog"
                aria-modal="true"
                aria-label="Approve Compliance Document"
                onMouseDown={(e) => {
                  if (e.target === e.currentTarget) closeComplianceApprove()
                }}
              >
                <div className="w-[min(480px,calc(100vw-32px))] rounded-xl bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                  <div className="flex items-start justify-between gap-4 px-6 pt-6">
                    <div>
                      <div className="text-base font-semibold text-foreground">
                        Approve Document
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        This action will mark the document as fully approved by compliance and make it ready to be published.
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={closeComplianceApprove}
                      className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label="Close"
                    >
                      <span className="text-xl leading-none">×</span>
                    </button>
                  </div>
                  <div className="px-6 pb-6 pt-5">
                    <div className="mt-5 flex justify-end gap-3">
                      <button
                        type="button"
                        onClick={closeComplianceApprove}
                        className="h-9 rounded-lg border border-foreground/15 bg-card px-5 text-xs font-medium text-foreground hover:bg-accent"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={handleComplianceApprove}
                        disabled={actionLoading}
                        className="h-9 rounded-lg bg-emerald-600 px-5 text-xs font-semibold text-white hover:bg-emerald-600/90 disabled:opacity-50"
                      >
                        {actionLoading ? "Approving..." : "Approve Document"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>,
              document.body
            )
          : null}

        {/* ── SME Approve modal ── */}
        {smeApproveOpen && typeof document !== "undefined"
          ? createPortal(
              <div
                className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
                role="dialog"
                aria-modal="true"
                aria-label="Approve SME Document"
                onMouseDown={(e) => {
                  if (e.target === e.currentTarget) closeSmeApprove()
                }}
              >
                <div className="w-[min(480px,calc(100vw-32px))] rounded-xl bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                  <div className="flex items-start justify-between gap-4 px-6 pt-6">
                    <div>
                      <div className="text-base font-semibold text-foreground">
                        Approve Document
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        This action will send the document to marketing review.
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={closeSmeApprove}
                      className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label="Close"
                    >
                      <span className="text-xl leading-none">×</span>
                    </button>
                  </div>
                  <div className="px-6 pb-6 pt-5">
                    <div className="mt-5 flex justify-end gap-3">
                      <button
                        type="button"
                        onClick={closeSmeApprove}
                        className="h-9 rounded-lg border border-foreground/15 bg-card px-5 text-xs font-medium text-foreground hover:bg-accent"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={handleSmeApprove}
                        disabled={actionLoading}
                        className="h-9 rounded-lg bg-emerald-600 px-5 text-xs font-semibold text-white hover:bg-emerald-600/90 disabled:opacity-50"
                      >
                        {actionLoading ? "Approving..." : "Approve Document"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>,
              document.body
            )
          : null}

        {/* ── Reject modal ── */}
        {rejectOpen && typeof document !== "undefined"
          ? createPortal(
              <div
                className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
                role="dialog"
                aria-modal="true"
                aria-label="Reject content"
                onMouseDown={(e) => {
                  if (e.target === e.currentTarget) closeReject()
                }}
              >
                <div className="w-[min(560px,calc(100vw-32px))] rounded-xl bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                  <div className="flex items-start justify-between gap-4 px-6 pt-6">
                    <div>
                      <div className="text-base font-semibold text-foreground">
                        Reject Content
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        This action will reject the content. Please provide a
                        clear rationale for the rejection.
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={closeReject}
                      className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label="Close"
                    >
                      <span className="text-xl leading-none">×</span>
                    </button>
                  </div>

                  {rejectStep === "form" ? (
                    <div className="px-6 pb-6 pt-5">
                      <label className="text-sm font-semibold text-foreground">
                        Comments
                      </label>
                      <textarea
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        placeholder="Short note explaining why it's rejected and what went wrong."
                        className="mt-2 h-28 w-full resize-none rounded-lg border border-foreground/15 bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#5BC0EB]/40"
                      />

                      <div className="mt-3 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-600 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        <span>
                          Rejected documents will be closed and cannot be
                          published unless resubmitted.
                        </span>
                      </div>

                      <div className="mt-5 flex justify-end gap-3">
                        <button
                          type="button"
                          onClick={closeReject}
                          className="h-9 rounded-lg border border-foreground/15 bg-card px-5 text-xs font-medium text-foreground hover:bg-accent"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={executeReject}
                          disabled={actionLoading}
                          className="h-9 rounded-lg bg-red-500 px-5 text-xs font-semibold text-white hover:bg-red-500/90 disabled:opacity-50"
                        >
                          Reject Document
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="px-6 pb-6 pt-6">
                      <div className="rounded-lg bg-muted px-6 py-8 text-center">
                        <img
                          src="/documents/fileRightClickIcon.svg"
                          alt=""
                          className="mx-auto h-20 w-20"
                        />
                        <p className="mx-auto mt-4 max-w-[420px] text-xs text-muted-foreground">
                          The document is now back with marketing and can be
                          reassigned for review when ready.
                        </p>
                      </div>

                      <div className="mt-5 flex justify-end">
                        <button
                          type="button"
                          onClick={closeReject}
                          className="h-9 rounded-lg bg-red-600 px-5 text-xs font-semibold text-white hover:bg-red-600/90"
                        >
                          Close
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>,
              document.body
            )
          : null}

        {/* ── Request Changes modal ── */}
        {requestChangesOpen && typeof document !== "undefined"
          ? createPortal(
              <div
                className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-sm"
                role="dialog"
                aria-modal="true"
                aria-label="Request changes"
                onMouseDown={(e) => {
                  if (e.target === e.currentTarget) closeRequestChanges()
                }}
              >
                <div className="w-[min(560px,calc(100vw-32px))] rounded-xl bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
                  <div className="flex items-start justify-between gap-4 px-6 pt-6">
                    <div>
                      <div className="text-base font-semibold text-foreground">
                        Request Changes
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Please provide details about what changes are needed.
                        This will be sent back to the submitter.
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={closeRequestChanges}
                      className="grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label="Close"
                    >
                      <span className="text-xl leading-none">×</span>
                    </button>
                  </div>

                  {requestChangesStep === "form" ? (
                    <div className="px-6 pb-6 pt-5">
                      <label className="text-sm font-semibold text-foreground">
                        What needs to be changed?
                      </label>
                      <textarea
                        value={requestChangesReason}
                        onChange={(e) =>
                          setRequestChangesReason(e.target.value)
                        }
                        placeholder="Describe the issue or required corrections..."
                        className="mt-2 h-28 w-full resize-none rounded-lg border border-foreground/15 bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#5BC0EB]/40"
                      />

                      <div className="mt-5 flex justify-end gap-3">
                        <button
                          type="button"
                          onClick={closeRequestChanges}
                          className="h-9 rounded-lg border border-foreground/15 bg-card px-5 text-xs font-medium text-foreground hover:bg-accent"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={executeRequestChanges}
                          disabled={actionLoading}
                          className="h-9 rounded-lg bg-[#128BDA] px-5 text-xs font-semibold text-white hover:bg-[#128BDA]/90 disabled:opacity-50"
                        >
                          Request Changes
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="px-6 pb-6 pt-6">
                      <div className="rounded-lg bg-muted px-6 py-8 text-center">
                        <img
                          src="/documents/fileRightClickIcon.svg"
                          alt=""
                          className="mx-auto h-20 w-20"
                        />
                        <p className="mx-auto mt-4 max-w-[420px] text-xs text-muted-foreground">
                          The document has been returned to the marketing user
                          for revision. After the revised version is uploaded, it
                          will be reassigned to you for review.
                        </p>
                      </div>

                      <div className="mt-5 flex justify-end">
                        <button
                          type="button"
                          onClick={closeRequestChanges}
                          className="h-9 rounded-lg bg-[#128BDA] px-5 text-xs font-semibold text-white hover:bg-[#128BDA]/90"
                        >
                          Close
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>,
              document.body
            )
          : null}
      </div>
    </MainLayout>
  )
}
/*
CI TESTING
*/