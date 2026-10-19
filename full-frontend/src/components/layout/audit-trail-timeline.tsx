import * as React from "react"
import { cn } from "@/lib/utils"
import {
  CheckCircle2,
  XCircle,
  MessageSquare,
  Upload,
  ArrowRight,
  Bot,
  Flag,
  Zap,
  RefreshCw,
} from "lucide-react"
import { documentsApi, auditApi } from "@/lib/api"

type TimelineEvent = {
  id: string
  source: "workflow_step" | "audit_event" | "content_comment"
  event_type: string
  timestamp: string
  time: string
  date: string
  workflow_stage: string
  previous_stage: string | null
  user: string
  user_role: string
  user_id?: string | null
  is_ai: boolean
  description: string
  details: string | null
  comment: string | null
  finding: {
    id?: string
    code?: string
    title?: string
    description?: string
    risk_level?: string
    location?: string
    finding_id?: string
    finding_code?: string
    finding_title?: string
    finding_description?: string
  } | null
  finding_comment: string | null
  finding_suggestion: string | null
  triggered_by_user_id?: string | null
  grouping_user_id?: string | null
  grouping_user_name?: string
}

type UserGroup = {
  user_id: string
  user_name: string
  user_role: string
  events: TimelineEvent[]
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  uploaded: "Document Uploaded",
  reuploaded: "Document Re-uploaded",
  claim: "Review Claimed",
  claimed: "Review Claimed",
  approve: "Approved",
  sme_approve: "SME Approved",
  submit_to_compliance: "Sent to Compliance",
  submit_to_marketing: "Sent to Marketing",
  approve_and_lock: "Approved & Locked",
  reject: "Rejected",
  request_changes: "Changes Requested",
  assigned: "Reviewer Assigned",
  publish: "Published",
  finding_accepted: "AI Finding Accepted",
  finding_accepted_global: "AI Finding Accepted",
  finding_accepted_local: "AI Finding Accepted (Suggestion Selected)",
  finding_rejected: "AI Finding Rejected",
  finding_rejected_global: "AI Finding Rejected",
  finding_comment_added: "Feedback on Finding",
  finding_suggestion_added: "Alternate Suggestion",
  finding_suggestion_edited: "Alternate Suggestion Edited",
  comment_added: "Comment Added",
  ai_analysis_started: "AI Analysis Started",
  ai_analysis_completed: "AI Analysis Completed",
  ai_analysis_skipped: "AI Analysis Skipped",
  ai_analysis_failed: "AI Analysis Failed",
  ai_classification_completed: "Classification Completed",
  workflow_stage_changed: "Stage Changed",
  review_claimed: "Review Claimed",
  review_completed: "Review Completed",
  changes_requested: "Changes Requested",
  document_locked: "Document Locked",
  document_published: "Document Published",
  document_upload: "Document Uploaded",
}

const STAGE_LABELS: Record<string, string> = {
  sme_review: "SME Review",
  marketing_review: "Marketing Review",
  compliance_review: "Compliance Review",
  needs_revision: "Needs Revision",
  approved: "Approved",
  published: "Published",
  rejected: "Rejected",
  document_upload: "Document Upload",
}

type EventMeta = { icon: React.ReactNode; dotClass: string; cardClass: string }

function getEventMeta(eventType: string, isAI: boolean): EventMeta {
  const t = (eventType || "").toLowerCase()

  if (isAI) {
    return {
      icon: <Bot className="h-3.5 w-3.5" />,
      dotClass: "bg-violet-500",
      cardClass:
        "border-l-violet-300 bg-violet-50/40 dark:border-l-violet-600 dark:bg-violet-950/40",
    }
  }
  if (t.includes("reject") || t === "ai_analysis_failed") {
    return {
      icon: <XCircle className="h-3.5 w-3.5" />,
      dotClass: "bg-red-500",
      cardClass: "border-l-red-300 bg-red-50/40 dark:border-l-red-600 dark:bg-red-950/40",
    }
  }
  if (
    t.includes("approve") ||
    t.includes("accepted") ||
    t === "document_published" ||
    t === "document_locked" ||
    t === "publish"
  ) {
    return {
      icon: <CheckCircle2 className="h-3.5 w-3.5" />,
      dotClass: "bg-emerald-500",
      cardClass:
        "border-l-emerald-300 bg-emerald-50/40 dark:border-l-emerald-600 dark:bg-emerald-950/40",
    }
  }
  if (t.includes("upload") || t === "reuploaded") {
    return {
      icon: <Upload className="h-3.5 w-3.5" />,
      dotClass: "bg-blue-500",
      cardClass: "border-l-blue-300 bg-blue-50/40 dark:border-l-blue-600 dark:bg-blue-950/40",
    }
  }
  if (t.includes("comment") || t.includes("feedback")) {
    return {
      icon: <MessageSquare className="h-3.5 w-3.5" />,
      dotClass: "bg-amber-500",
      cardClass: "border-l-amber-300 bg-amber-50/40 dark:border-l-amber-600 dark:bg-amber-950/40",
    }
  }
  if (t.includes("finding") || t.includes("suggestion")) {
    return {
      icon: <Flag className="h-3.5 w-3.5" />,
      dotClass: "bg-orange-500",
      cardClass:
        "border-l-orange-300 bg-orange-50/40 dark:border-l-orange-600 dark:bg-orange-950/40",
    }
  }
  if (t.includes("ai_analysis") || t.includes("classification")) {
    return {
      icon: <Zap className="h-3.5 w-3.5" />,
      dotClass: "bg-violet-500",
      cardClass:
        "border-l-violet-300 bg-violet-50/40 dark:border-l-violet-600 dark:bg-violet-950/40",
    }
  }
  if (t.includes("stage") || t.includes("claim") || t.includes("submit") || t.includes("reupload")) {
    return {
      icon: <RefreshCw className="h-3.5 w-3.5" />,
      dotClass: "bg-sky-500",
      cardClass: "border-l-sky-300 bg-sky-50/40 dark:border-l-sky-600 dark:bg-sky-950/40",
    }
  }
  return {
    icon: <ArrowRight className="h-3.5 w-3.5" />,
    dotClass: "bg-slate-400",
    cardClass: "border-l-slate-200 bg-card dark:border-l-slate-600",
  }
}

function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
  return (
    <div
      className="grid shrink-0 place-items-center rounded-full bg-foreground/10 text-[11px] font-semibold text-foreground"
      style={{ width: size, height: size }}
      aria-hidden
    >
      {initials || "U"}
    </div>
  )
}

function formatRoleDisplay(role: string): string {
  if (!role) return "User"
  const parts = role.split(",").map((p) => p.trim().toLowerCase()).filter(Boolean)
  if (parts.length === 0) return "User"

  const mapped = parts.map((r) => {
    if (r === "sme") return "SME"
    if (r === "marketing") return "Marketing"
    if (r === "compliance") return "Compliance"
    if (r === "super_admin" || r === "super admin") return "Super Admin"
    if (r === "ai" || r === "system") return "AI"
    if (r === "admin") return "Admin"
    if (r === "unknown") return "User"
    return r.replace(/\b\w/g, (c) => c.toUpperCase())
  })

  const unique = Array.from(new Set(mapped)).filter(Boolean)
  const finalRoles = unique.filter((u) => u !== "User" || unique.length === 1)

  if (finalRoles.length === 0) return "User"
  return finalRoles.join(", ")
}

function getRoleBadgeStyle(role: string): string {
  const r = (role || "").toLowerCase()
  if (r.includes("sme")) return "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300"
  if (r.includes("marketing")) return "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300"
  if (r.includes("compliance")) return "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300"
  if (r.includes("admin")) return "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300"
  if (r.includes("system") || r === "ai") return "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300"
  return "bg-muted text-muted-foreground"
}

function getStageLabel(stage: string | null | undefined): string {
  if (!stage) return ""
  const key = stage.trim().toLowerCase().replace(/\s+/g, "_")
  return STAGE_LABELS[key] || stage.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

function getEventLabel(event: TimelineEvent): string {
  const action = (event.event_type || "").toLowerCase()
  const prev = (event.previous_stage || "").toLowerCase()

  if (action === "approve") {
    if (prev === "sme_review") return "Sent to Marketing Reviewer"
    if (prev === "marketing_review") return "Sent to Compliance"
    return EVENT_TYPE_LABELS.approve
  }

  if (EVENT_TYPE_LABELS[action]) return EVENT_TYPE_LABELS[action]

  return action
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatEventDetails(event: TimelineEvent): string {
  const parts: string[] = []

  if (event.finding) {
    const f = event.finding
    const code = f.finding_code || f.code || null
    const title = f.finding_title || f.title || null
    const location = f.location || null
    const risk = f.risk_level || null
    const findingParts: string[] = []
    if (code && code !== "N/A") findingParts.push(code)
    if (risk) findingParts.push(`(${risk.charAt(0).toUpperCase() + risk.slice(1).toLowerCase()} Risk)`)
    if (location && location !== "N/A") findingParts.push(`at ${location}`)
    if (title && title !== "AI Finding") {
      if (findingParts.length > 0) {
        parts.push(findingParts.join(" "))
        parts.push(title)
      } else {
        parts.push(title)
      }
    } else if (findingParts.length > 0) {
      parts.push(`Finding ${findingParts.join(" ")}`)
    }
  }
  if (event.finding_comment) parts.push(event.finding_comment)
  if (event.finding_suggestion) parts.push(`Suggestion: ${event.finding_suggestion}`)
  if (event.comment) parts.push(event.comment)

  const desc = (event.description || "").trim()
  if (desc && !desc.toLowerCase().startsWith("workflow action:")) {
    parts.push(desc)
  }

  if (event.details && !event.finding && !event.comment && !event.finding_comment) {
    try {
      const d = typeof event.details === "string" ? JSON.parse(event.details) : event.details
      if (typeof d === "object" && d !== null) {
        const dp: string[] = []
        if (d.finding_code) dp.push(String(d.finding_code))
        if (d.risk_level)
          dp.push(
            `(${String(d.risk_level).charAt(0).toUpperCase() + String(d.risk_level).slice(1).toLowerCase()} Risk)`
          )
        if (d.location) dp.push(`at ${String(d.location)}`)
        if (dp.length > 0) parts.push(`Finding ${dp.join(" ")}`)
        if (d.comment_content) parts.push(String(d.comment_content))
        if (d.suggestion_text) parts.push(`Suggestion: ${String(d.suggestion_text)}`)
        if (d.reject_reason) parts.push(`Reason: ${String(d.reject_reason)}`)
      } else if (typeof event.details === "string") {
        parts.push(event.details)
      }
    } catch {
      if (typeof event.details === "string") parts.push(event.details)
    }
  }

  if (parts.length === 0 && event.previous_stage && event.workflow_stage) {
    const from = getStageLabel(event.previous_stage)
    const to = getStageLabel(event.workflow_stage)
    if (from && to && from !== to) parts.push(`${from} → ${to}`)
  }

  if (parts.length === 0) return ""
  return parts.join(" · ")
}

/** Group consecutive events by actor; AI events share one "AI Compliance" section. */
function groupEventsByUser(events: TimelineEvent[]): UserGroup[] {
  const groups: UserGroup[] = []
  let current: UserGroup | null = null

  for (const ev of events) {
    const uid = ev.is_ai ? "ai-system" : ev.grouping_user_id || ev.user_id || "system"
    const uname = ev.is_ai ? "AI Compliance" : ev.grouping_user_name || ev.user || "System"
    const urole = ev.is_ai ? "ai" : ev.user_role || "unknown"

    if (!current || current.user_id !== uid) {
      if (current) groups.push(current)
      current = { user_id: uid, user_name: uname, user_role: urole, events: [] }
    }
    current.events.push(ev)
  }
  if (current) groups.push(current)
  return groups
}

/** Format a UTC ISO timestamp into the viewer's local timezone */
function formatLocalTs(iso: string | null | undefined): { time: string; date: string } {
  if (!iso) return { time: "", date: "" }
  const raw = iso.endsWith("Z") ? iso : iso + "Z"
  const d = new Date(raw)
  if (isNaN(d.getTime())) return { time: iso, date: "" }
  const time = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
  const date = d.toLocaleDateString("en-US", { day: "2-digit", month: "short", year: "numeric" })
  return { time, date }
}

function TimelineEventCard({ event }: { event: TimelineEvent }) {
  const label = getEventLabel(event)
  const detail = formatEventDetails(event)
  const meta = getEventMeta(event.event_type, event.is_ai)
  const stageLabel = getStagePillLabel(event)
  const { time, date } = formatLocalTs(event.timestamp)

  return (
    <div
      className={cn(
        "rounded-lg border border-border border-l-4 px-3 py-2 shadow-sm",
        meta.cardClass
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          <span className="text-muted-foreground">{meta.icon}</span>
          <span className="text-sm font-medium text-foreground">{label}</span>
          {stageLabel ? (
            <span className="rounded-md bg-card/80 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground ring-1 ring-border">
              {stageLabel}
            </span>
          ) : null}
        </div>
        <div className="shrink-0 text-right">
          <span className="font-mono text-[11px] text-muted-foreground whitespace-nowrap">{time}</span>
          {date ? (
            <div className="font-mono text-[10px] text-muted-foreground/70">{date}</div>
          ) : null}
        </div>
      </div>
      {detail ? <p className="mt-1.5 text-xs leading-relaxed text-foreground/70">{detail}</p> : null}
    </div>
  )
}


/**
 * Some audit events (notably `approve`) are emitted with `workflow_stage` inconsistent
 * with the actual "to" stage in `previous_stage`. This keeps the UI stage pill correct
 * even when the backend payload is imperfect.
 */
function getStagePillLabel(event: TimelineEvent): string {
  const eventType = (event.event_type || "").toLowerCase()
  const prev = (event.previous_stage || "").toLowerCase().trim()

  if (eventType === "approve") {
    if (prev === "sme_review") return getStageLabel("marketing_review")
    if (prev === "marketing_review") return getStageLabel("compliance_review")
  }

  if (eventType === "sme_approve") {
    return getStageLabel("marketing_review")
  }

  return getStageLabel(event.workflow_stage)
}

function UserGroupSection({ group, isLastGroup }: { group: UserGroup; isLastGroup: boolean }) {
  const isAiGroup = group.user_id === "ai-system"
  const roleLabel = formatRoleDisplay(group.user_role)

  return (
    <div className={cn("relative", !isLastGroup && "mb-5")}>
      {/* Actor header */}
      <div className="mb-2 flex items-center gap-2.5 rounded-lg border border-border/60 bg-muted/30 px-3 py-2">
        {isAiGroup ? (
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-900/50">
            <Bot className="h-4 w-4 text-violet-600 dark:text-violet-300" />
          </div>
        ) : (
          <Avatar name={group.user_name} size={32} />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground">{group.user_name}</span>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold",
                getRoleBadgeStyle(group.user_role)
              )}
            >
              {roleLabel}
            </span>
          </div>
          <span className="text-[11px] text-muted-foreground">
            {group.events.length} action{group.events.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Events in this group */}
      <div className="relative ml-3 space-y-2 border-l border-foreground/10 pl-4">
        {group.events.map((event, ei) => (
          <TimelineEventCard key={event.id || `ev-${ei}`} event={event} />
        ))}
      </div>
    </div>
  )
}

export function AuditTrailTimeline({
  orgSlug,
  docId,
  reviewId,
}: {
  orgSlug?: string
  docId?: string
  reviewId?: string
}) {
  const [versionGroups, setVersionGroups] = React.useState<any[]>([])
  const [eventCount, setEventCount] = React.useState(0)
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    const id = docId || reviewId
    if (!id) return
    setLoading(true)
    const fetchFn = docId
      ? () => {
          if (!orgSlug?.trim()) {
            return Promise.reject(new Error("Missing organization context for document audit trail"))
          }
          return documentsApi.getDocumentUnifiedAuditTrail(orgSlug, docId)
        }
      : () => {
          if (!orgSlug?.trim()) {
            return Promise.reject(new Error("Missing organization context for review audit trail"))
          }
          return auditApi
            .getUnifiedAuditTrail(orgSlug, reviewId!)
            .then((data) => ({ ...data, version_groups: [] }))
        }
    fetchFn()
      .then((data: any) => {
        const evList = data.events || []
        setEventCount(evList.length)
        if (data.version_groups && data.version_groups.length > 0) {
          setVersionGroups(data.version_groups)
        } else {
          setVersionGroups([{ version_label: reviewId ? "Audit Trail" : "Version 1", events: evList }])
        }
      })
      .catch((err: unknown) => console.error("Audit trail load failed:", err))
      .finally(() => setLoading(false))
  }, [docId, reviewId, orgSlug])

  if (loading) {
    return (
      <div className="space-y-4 py-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex gap-3">
            <div className="mt-1 h-8 w-8 animate-pulse rounded-full bg-foreground/8" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-24 animate-pulse rounded bg-foreground/8" />
              <div className="h-14 animate-pulse rounded-lg bg-foreground/5" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  if (versionGroups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-center">
        <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <ArrowRight className="h-5 w-5 text-muted-foreground" />
        </div>
        <p className="text-sm font-medium text-foreground">No events recorded yet</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Workflow actions will appear here once the review progresses
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-1">
      <div className="mb-4 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {eventCount} event{eventCount !== 1 ? "s" : ""} recorded
        </span>
        <span className="text-xs text-muted-foreground">
          {versionGroups.length} version{versionGroups.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="space-y-8">
        {versionGroups.map((group, gi) => {
          const events: TimelineEvent[] = group.events || []
          const userGroups = groupEventsByUser(events)

          return (
            <div key={group.version_label || `g-${gi}`}>
              <div className="sticky top-0 z-10 mb-4">
                <div className="flex items-center gap-3 rounded-xl border border-border bg-card/90 backdrop-blur-sm px-4 py-2.5 shadow-sm">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                    {gi + 1}
                  </div>
                  <span className="flex-1 text-sm font-semibold text-foreground">
                    {group.version_label || `Version ${gi + 1}`}
                  </span>
                  <span className="shrink-0 text-[11px] text-muted-foreground">
                    {userGroups.length} participant{userGroups.length !== 1 ? "s" : ""}
                  </span>
                </div>
              </div>

              <div className="space-y-1">
                {userGroups.map((userGroup, ugi) => (
                  <UserGroupSection
                    key={`${group.version_label}-${userGroup.user_id}-${ugi}`}
                    group={userGroup}
                    isLastGroup={ugi === userGroups.length - 1}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
