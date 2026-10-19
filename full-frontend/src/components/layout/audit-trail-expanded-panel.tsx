import * as React from "react"
import { cn } from "@/lib/utils"
import {
  CalendarDays,
  ChevronDown,
  Clock,
} from "lucide-react"
import { auditApi } from "@/lib/api"
import { AuditTrailTimeline } from "./audit-trail-timeline"

type WorkflowKind = "success" | "warning" | "danger" | "info"

type WorkflowRow = {
  kind: WorkflowKind
  title: string
  stage: string
  user: string
  /** When set, renders as plain text "Completed by [user]" instead of avatar + name */
  userPrefix?: string
  date: string
  time: string
  comment?: string
}

function Avatar({ name, size = 22 }: { name: string; size?: number }) {
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
      aria-hidden
    >
      {initials || "U"}
    </div>
  )
}


function RightClickCircleIcon({ fill }: { fill: string }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M13.5672 7.68281C13.6253 7.74086 13.6714 7.80979 13.7029 7.88566C13.7343 7.96154 13.7505 8.04287 13.7505 8.125C13.7505 8.20713 13.7343 8.28846 13.7029 8.36434C13.6714 8.44021 13.6253 8.50914 13.5672 8.56719L9.19219 12.9422C9.13415 13.0003 9.06522 13.0464 8.98934 13.0779C8.91347 13.1093 8.83214 13.1255 8.75 13.1255C8.66787 13.1255 8.58654 13.1093 8.51067 13.0779C8.43479 13.0464 8.36586 13.0003 8.30782 12.9422L6.43282 11.0672C6.31554 10.9499 6.24966 10.7909 6.24966 10.625C6.24966 10.4591 6.31554 10.3001 6.43282 10.1828C6.55009 10.0655 6.70915 9.99965 6.875 9.99965C7.04086 9.99965 7.19992 10.0655 7.31719 10.1828L8.75 11.6164L12.6828 7.68281C12.7409 7.6247 12.8098 7.5786 12.8857 7.54715C12.9615 7.5157 13.0429 7.49951 13.125 7.49951C13.2071 7.49951 13.2885 7.5157 13.3643 7.54715C13.4402 7.5786 13.5091 7.6247 13.5672 7.68281ZM18.125 10C18.125 11.607 17.6485 13.1779 16.7557 14.514C15.8629 15.8502 14.594 16.8916 13.1093 17.5065C11.6247 18.1215 9.99099 18.2824 8.4149 17.9689C6.8388 17.6554 5.39106 16.8815 4.25476 15.7452C3.11846 14.6089 2.34463 13.1612 2.03112 11.5851C1.71762 10.009 1.87852 8.37535 2.49348 6.8907C3.10844 5.40605 4.14985 4.1371 5.486 3.24431C6.82214 2.35152 8.39303 1.875 10 1.875C12.1542 1.87727 14.2195 2.73403 15.7427 4.25727C17.266 5.78051 18.1227 7.84581 18.125 10ZM16.875 10C16.875 8.64025 16.4718 7.31104 15.7164 6.18045C14.9609 5.04987 13.8872 4.16868 12.631 3.64833C11.3747 3.12798 9.99238 2.99183 8.65876 3.2571C7.32514 3.52237 6.10013 4.17716 5.13864 5.13864C4.17716 6.10013 3.52238 7.32513 3.2571 8.65875C2.99183 9.99237 3.12798 11.3747 3.64833 12.6309C4.16868 13.8872 5.04987 14.9609 6.18046 15.7164C7.31105 16.4718 8.64026 16.875 10 16.875C11.8227 16.8729 13.5702 16.1479 14.8591 14.8591C16.1479 13.5702 16.8729 11.8227 16.875 10Z" fill={fill}/>
    </svg>
  )
}

function WorkflowKindIcon({ kind }: { kind: WorkflowKind }) {
  const wrapClass =
    "grid h-7 w-7 place-items-center rounded-full bg-[#F3F5F7] shadow-[0_1px_6px_rgba(0,0,0,0.08)]"

  if (kind === "success") {
    return (
      <span className={wrapClass}>
        <img src="/greenRightClick/Default.svg" alt="approved" className="h-[18px] w-[18px]" />
      </span>
    )
  }
  if (kind === "warning") {
    return (
      <span className={wrapClass}>
        <RightClickCircleIcon fill="#F1C21B" />
      </span>
    )
  }
  if (kind === "danger") {
    return (
      <span className={wrapClass}>
        <RightClickCircleIcon fill="#FF383C" />
      </span>
    )
  }
  return (
    <span className={wrapClass}>
      <img src="/shared/PaperPlaneTilt.svg" alt="info" className="h-[18px] w-[18px]" />
    </span>
  )
}

function CommentBox({ text }: { text: string }) {
  return (
    <div className="rounded-lg bg-[#F7F8F9] px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <img src="/shared/chatIcon.svg" alt="comment" className="h-4 w-4" />
        Comment
      </div>
      <div className="mt-1.5 text-xs text-muted-foreground">{text}</div>
    </div>
  )
}

function WorkflowRowView({
  row,
  isOpen,
  onToggle,
  children,
}: {
  row: WorkflowRow
  isOpen?: boolean
  onToggle?: () => void
  children?: React.ReactNode
}) {
  return (
    <div className="rounded-xl bg-white">
      {/* Row header */}
      <div className="grid grid-cols-[28px_28px_170px_140px_minmax(140px,220px)_104px_84px] items-center gap-2 px-2 py-3">
        {onToggle ? (
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              "grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-[#F7F8F9] hover:text-foreground",
              isOpen && "bg-[#F7F8F9] text-foreground"
            )}
            aria-label={isOpen ? "Collapse section" : "Expand section"}
          >
            <ChevronDown className={cn("h-4 w-4 transition-transform", isOpen && "rotate-180")} />
          </button>
        ) : (
          <div className="h-7 w-7" />
        )}

        <WorkflowKindIcon kind={row.kind} />

        <div className="text-xs font-semibold text-foreground">{row.title}</div>

        <div className="text-xs text-muted-foreground">{row.stage}</div>

        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {row.userPrefix ? (
            <span>
              {row.userPrefix}{" "}
              <span className="font-semibold text-foreground">{row.user}</span>
            </span>
          ) : (
            <>
              <Avatar name={row.user} />
              <span className="truncate text-foreground">{row.user}</span>
            </>
          )}
        </div>

        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <CalendarDays className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{row.date}</span>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="h-3.5 w-3.5 shrink-0" />
          <span>{row.time}</span>
        </div>
      </div>

      {/* Expanded content — sits inside the same ghost card */}
      {children && isOpen ? (
        <div className="px-3 pb-3">
          {children}
        </div>
      ) : null}
    </div>
  )
}

// ── Mapping helpers ────────────────────────────────────────────────

const ACTION_KIND: Record<string, WorkflowKind> = {
  approve: "success",
  sme_approve: "success",
  approve_and_lock: "success",
  publish: "success",
  approved: "success",
  reject: "danger",
  request_changes: "danger",
  needs_revision: "danger",
  claim: "warning",
  claimed: "warning",
}

const ACTION_TITLE: Record<string, string> = {
  approve: "Approved",
  sme_approve: "SME Approved",
  approve_and_lock: "Approved & Locked",
  publish: "Published",
  approved: "Approved",
  reject: "Rejected",
  request_changes: "Change Requested",
  needs_revision: "Change Requested",
  claim: "Claimed for Review",
  claimed: "Claimed for Review",
  uploaded: "Document Uploaded",
  reuploaded: "Document Re-uploaded",
  submit_to_compliance: "Sent to Compliance",
  submit_to_marketing: "Sent to Marketing",
  assigned: "Reviewer Assigned",
}

const STAGE_LABEL: Record<string, string> = {
  sme_review: "SME Review",
  marketing_review: "Marketing Review",
  compliance_review: "Compliance Review",
  needs_revision: "Needs Revision",
  publish: "Approved",
  approved: "Approved",
  published: "Published",
  rejected: "Rejected",
  document_upload: "Document Upload",
}

// ── Main component ────────────────────────────────────────────────

type AuditEvent = {
  type: "audit_event"
  time: string
  date: string
  user: string
  event: string
  details: string
  event_type: string
}

type GeneralComment = {
  type: "general_comment"
  id: string
  content: string
  time: string
  date: string
  author: string
  author_role: string
  created_at: string
}

type WorkflowComment = {
  type: "workflow_comment"
  content: string
  time: string
  date: string
  author: string
}

type WorkflowStepWithEvents = WorkflowRow & { 
  auditEvents?: AuditEvent[]
  workflowComment?: WorkflowComment
  generalComments?: GeneralComment[]
}

export function AuditTrailExpandedPanel({
  orgSlug,
  reviewId,
  docId,
}: {
  orgSlug?: string
  reviewId?: string
  docId?: string
}) {
  // Use the new unified timeline component — prefer docId (document-level), fall back to reviewId
  return <AuditTrailTimeline orgSlug={orgSlug} docId={docId} reviewId={reviewId} />
}

// Legacy implementation kept for reference but not used
function AuditTrailExpandedPanelLegacy({
  orgSlug,
  reviewId,
}: {
  orgSlug?: string
  reviewId?: string
}) {
  const [steps, setSteps] = React.useState<WorkflowStepWithEvents[]>([])
  const [auditEvents, setAuditEvents] = React.useState<AuditEvent[]>([])
  const [open, setOpen] = React.useState<Record<string, boolean>>({})
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    if (!reviewId || !orgSlug?.trim()) return
    setLoading(true)
    auditApi.getAuditTrail(orgSlug, reviewId)
      .then((data: any) => {
        // Handle new response structure with workflow_steps containing audit_events
        const workflowData = data.workflow_steps || (Array.isArray(data) ? data : [])
        
        const mapped: WorkflowStepWithEvents[] = workflowData.map((r: any) => {
          const action = (r.action || "").toLowerCase()
          const previousStage = r.previous_stage || ""
          
          // Match the title logic from document-right-panel
          let title = ""
          if (action === "approve") {
            if (previousStage === "sme_review") {
              title = "Sent to Marketing Reviewer"
            } else if (previousStage === "marketing_review") {
              title = "Sent to Compliance"
            } else {
              title = "Approved"
            }
          } else if (action === "sme_approve") {
            title = "Sent to Marketing Reviewer"
          } else if (action === "approve_and_lock") {
            title = "Approve & Lock"
          } else if (action === "reject") {
            title = "Rejected"
          } else if (action === "request_changes") {
            title = "Change Requested"
          } else if (action === "claim" || action === "claimed") {
            title = "Claimed for Review"
          } else if (action === "uploaded") {
            title = "Document Uploaded"
          } else if (action === "reuploaded") {
            title = "Document Re-uploaded"
          } else if (action === "submit_to_compliance") {
            title = "Sent to Compliance"
          } else if (action === "submit_to_marketing") {
            title = "Sent to Marketing"
          } else if (action === "assigned") {
            title = "Reviewer Assigned"
          } else if (action === "publish") {
            title = "Published"
          } else {
            title = ACTION_TITLE[action] ?? r.event?.replace("Status: ", "") ?? "Workflow Step"
          }
          
          // Use previous_stage for display like document-right-panel
          const displayStage = previousStage || r.stage || ""
          
          const fmtDate = (iso: string) => iso ? new Date(iso).toLocaleDateString("en-US", { day: "2-digit", month: "short", year: "numeric" }) : ""
          const fmtTime = (iso: string) => iso ? new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }) : ""

          return {
            kind: ACTION_KIND[action] ?? "info",
            title: title,
            stage: STAGE_LABEL[displayStage] ?? displayStage ?? "",
            user: r.user || "System",
            date: fmtDate(r.date),
            time: fmtTime(r.time),
            comment: r.workflow_comment?.content || (r.details && !r.details.startsWith("Action:") && !r.details.startsWith("Workflow step")
              ? r.details
              : undefined),
            workflowComment: r.workflow_comment ? {
              ...r.workflow_comment,
              date: fmtDate(r.workflow_comment.date),
              time: fmtTime(r.workflow_comment.time),
            } : undefined,
            generalComments: (r.general_comments || []).map((c: any) => ({
              ...c,
              date: fmtDate(c.date),
              time: fmtTime(c.time),
            })),
            auditEvents: (r.audit_events || []).map((e: any) => ({
              ...e,
              date: fmtDate(e.date),
              time: fmtTime(e.time),
            })),
          }
        })
        setSteps(mapped)
        // Store audit events separately for backward compatibility
        const allEvents: AuditEvent[] = []
        mapped.forEach((step: any) => {
          if (step.auditEvents && step.auditEvents.length > 0) {
            allEvents.push(...step.auditEvents)
          }
        })
        setAuditEvents(allEvents)
        // Open first step by default
        if (mapped.length > 0) {
          setOpen({ "0": true })
        }
      })
      .catch((err: any) => {
        console.error("Failed to fetch audit trail for review:", err)
      })
      .finally(() => setLoading(false))
  }, [reviewId, orgSlug])

  const toggle = (key: string) =>
    setOpen((s) => ({ ...s, [key]: !s[key] }))

  if (loading) {
    return (
      <div className="py-4 text-center text-xs text-muted-foreground">
        Loading workflow steps...
      </div>
    )
  }

  if (steps.length === 0) {
    return (
      <div className="py-4 text-center text-xs text-muted-foreground">
        No workflow steps recorded yet.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* First level: Workflow Steps with nested events */}
      {steps.map((row, idx) => {
        const key = String(idx)
        const isOpen = !!open[key]
        const stepEvents = row.auditEvents || []
        
        return (
          <div key={key} className="space-y-2">
            <WorkflowRowView
              row={row}
              isOpen={isOpen}
              onToggle={() => toggle(key)}
            >
              <div className="space-y-3">
                {/* Workflow Step Comment (tied to action) */}
                {row.workflowComment ? (
                  <div>
                    <div className="text-xs font-semibold text-muted-foreground mb-1.5">Action Comment</div>
                    <CommentBox text={row.workflowComment.content} />
                  </div>
                ) : row.comment ? (
                  <CommentBox text={row.comment} />
                ) : null}
                
                {/* General Comments (not tied to action) */}
                {row.generalComments && row.generalComments.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-muted-foreground mb-1.5">General Comments</div>
                    <div className="space-y-2">
                      {row.generalComments.map((gc: GeneralComment) => (
                        <div key={gc.id} className="rounded-lg bg-[#F7F8F9] px-4 py-3">
                          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1.5">
                            <img src="/shared/chatIcon.svg" alt="comment" className="h-4 w-4" />
                            <span>{gc.author} ({gc.author_role})</span>
                            <span className="ml-auto">{gc.time} • {gc.date}</span>
                          </div>
                          <div className="text-xs text-muted-foreground">{gc.content}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                
                {/* Show "No additional details" only if there are no comments at all */}
                {!row.workflowComment && !row.comment && (!row.generalComments || row.generalComments.length === 0) && (
                  <div className="text-xs text-muted-foreground">No additional details.</div>
                )}
                
                {/* AI Finding Events Table - Nested under this workflow step */}
                {stepEvents.length > 0 && (
                  <div className="mt-3 rounded-lg border border-foreground/10 bg-white">
                    <div className="border-b border-foreground/10 px-3 py-2">
                      <div className="grid grid-cols-[100px_140px_200px_1fr] gap-2 text-xs font-semibold text-foreground">
                        <div>Timestamp</div>
                        <div>User</div>
                        <div>Event</div>
                        <div>Details</div>
                      </div>
                    </div>
                    <div className="divide-y divide-foreground/10">
                      {stepEvents.map((evt: AuditEvent, evtIdx: number) => (
                        <div key={evtIdx} className="grid grid-cols-[100px_140px_200px_1fr] gap-2 px-3 py-2 text-xs">
                          <div className="text-muted-foreground">{evt.time}</div>
                          <div className="text-foreground">{evt.user}</div>
                          <div className="text-foreground">{evt.event}</div>
                          <div className="text-muted-foreground">{evt.details}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </WorkflowRowView>
          </div>
        )
      })}
    </div>
  )
}
