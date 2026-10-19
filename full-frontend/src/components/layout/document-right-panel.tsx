import * as React from "react"
import { cn } from "@/lib/utils"
import { Clock, Maximize2, Minimize2 } from "lucide-react"
import type { MentionUser } from "@/components/layout/comment-trail"
// ── Avatar ────────────────────────────────────────────────────────

function Avatar({ name, size = 20 }: { name: string; size?: number }) {
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

// ── Workflow icon ─────────────────────────────────────────────────

type WorkflowKind = "info" | "warning" | "danger" | "success"

const RightClickCircleIcon = ({ fill }: { fill: string }) => (
  <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M13.5672 7.68281C13.6253 7.74086 13.6714 7.80979 13.7029 7.88566C13.7343 7.96154 13.7505 8.04287 13.7505 8.125C13.7505 8.20713 13.7343 8.28846 13.7029 8.36434C13.6714 8.44021 13.6253 8.50914 13.5672 8.56719L9.19219 12.9422C9.13415 13.0003 9.06522 13.0464 8.98934 13.0779C8.91347 13.1093 8.83214 13.1255 8.75 13.1255C8.66787 13.1255 8.58654 13.1093 8.51067 13.0779C8.43479 13.0464 8.36586 13.0003 8.30782 12.9422L6.43282 11.0672C6.31554 10.9499 6.24966 10.7909 6.24966 10.625C6.24966 10.4591 6.31554 10.3001 6.43282 10.1828C6.55009 10.0655 6.70915 9.99965 6.875 9.99965C7.04086 9.99965 7.19992 10.0655 7.31719 10.1828L8.75 11.6164L12.6828 7.68281C12.7409 7.6247 12.8098 7.5786 12.8857 7.54715C12.9615 7.5157 13.0429 7.49951 13.125 7.49951C13.2071 7.49951 13.2885 7.5157 13.3643 7.54715C13.4402 7.5786 13.5091 7.6247 13.5672 7.68281ZM18.125 10C18.125 11.607 17.6485 13.1779 16.7557 14.514C15.8629 15.8502 14.594 16.8916 13.1093 17.5065C11.6247 18.1215 9.99099 18.2824 8.4149 17.9689C6.8388 17.6554 5.39106 16.8815 4.25476 15.7452C3.11846 14.6089 2.34463 13.1612 2.03112 11.5851C1.71762 10.009 1.87852 8.37535 2.49348 6.8907C3.10844 5.40605 4.14985 4.1371 5.486 3.24431C6.82214 2.35152 8.39303 1.875 10 1.875C12.1542 1.87727 14.2195 2.73403 15.7427 4.25727C17.266 5.78051 18.1227 7.84581 18.125 10ZM16.875 10C16.875 8.64025 16.4718 7.31104 15.7164 6.18045C14.9609 5.04987 13.8872 4.16868 12.631 3.64833C11.3747 3.12798 9.99238 2.99183 8.65876 3.2571C7.32514 3.52237 6.10013 4.17716 5.13864 5.13864C4.17716 6.10013 3.52238 7.32513 3.2571 8.65875C2.99183 9.99237 3.12798 11.3747 3.64833 12.6309C4.16868 13.8872 5.04987 14.9609 6.18046 15.7164C7.31105 16.4718 8.64026 16.875 10 16.875C11.8227 16.8729 13.5702 16.1479 14.8591 14.8591C16.1479 13.5702 16.8729 11.8227 16.875 10Z" fill={fill} />
  </svg>
)

function WorkflowIcon({ kind }: { kind: WorkflowKind }) {
  const wrap =
    "grid h-7 w-7 shrink-0 place-items-center rounded-full bg-muted shadow-[0_1px_6px_rgba(0,0,0,0.08)] dark:shadow-[0_1px_6px_rgba(0,0,0,0.3)]"
  if (kind === "success")
    return <span className={wrap}><img src="/greenRightClick/Default.svg" alt="" className="h-[15px] w-[15px] dark:invert dark:opacity-90" /></span>
  if (kind === "warning")
    return <span className={wrap}><RightClickCircleIcon fill="#F1C21B" /></span>
  if (kind === "danger")
    return <span className={wrap}><RightClickCircleIcon fill="#FF383C" /></span>
  return (
    <span className={wrap}>
      <img src="/shared/PaperPlaneTilt.svg" alt="" className="h-[15px] w-[15px] dark:invert dark:opacity-90" />
    </span>
  )
}

// ── Types ─────────────────────────────────────────────────────────

export type WorkflowItem = {
  kind: WorkflowKind
  title: string
  stage: string
  user: string
  time: string
  highlight?: "green" | "orange"
  comment?: string
}

export type WorkflowGroup = {
  versionLabel: string
  items: WorkflowItem[]
}

export type CommentItem = {
  user: string
  tag?: string
  text: string
  time: string
}

export type CommentGroup = {
  versionLabel: string
  items: CommentItem[]
}

export type DocumentRightPanelProps = {
  workflowGroups: WorkflowGroup[]
  commentGroups: CommentGroup[]
  commentCount?: number
  mentionUsers?: MentionUser[]
  /** When false, shows only the Approval Workflow section */
  showComments?: boolean
  onApprovedClick?: () => void
  onSendComment?: (text: string, mentionedUserIds?: string[]) => void
  disabled?: boolean
  disabledMessage?: string
  /** Whether comments are shown in expanded full-width view */
  commentsExpanded?: boolean
  /** Toggle between inline comments and expanded full-width comments view */
  onCommentsExpandToggle?: () => void
  onCollapseClick?: () => void
  className?: string
  /** When this value changes (e.g. document id), comment list scroll anchor resets. */
  commentThreadKey?: string
}

function getRoleBadgeClasses(tag: string) {
  const t = tag.toLowerCase()
  if (t.includes("marketing")) return "bg-[#24A148] text-white"
  if (t.includes("sme")) return "bg-[#5BC0EB] text-white"
  if (t.includes("compliance")) return "bg-[#F1C21B] text-white"
  if (t.includes("admin")) return "bg-[#128BDA] text-white"
  if (t.includes("ai") || t.includes("profile")) return "bg-[#FF832B] text-white"
  return "bg-muted text-foreground"
}

/** Strips the leading @ from any @mention in comment body text for display. */
function renderCommentText(text: string): string {
  return text.replace(/@(\S+)/g, "$1")
}

// ── Component ─────────────────────────────────────────────────────

export function DocumentRightPanel({
  workflowGroups,
  commentGroups,
  commentCount = 0,
  mentionUsers,
  showComments = true,
  onApprovedClick,
  onSendComment,
  disabled = false,
  disabledMessage = "Claim the review to add comments",
  commentsExpanded = false,
  onCommentsExpandToggle,
  onCollapseClick,
  className,
  commentThreadKey = "",
}: DocumentRightPanelProps) {
  const groupedCommentCount = commentGroups.reduce((sum, group) => sum + group.items.length, 0)
  const effectiveCommentCount = Math.max(commentCount, groupedCommentCount)
  const workflowItemCount = React.useMemo(
    () => workflowGroups.reduce((sum, group) => sum + group.items.length, 0),
    [workflowGroups]
  )
  const workflowScrollRef = React.useRef<HTMLDivElement>(null)
  const prevWorkflowThreadKeyRef = React.useRef<string | undefined>(undefined)
  const prevWorkflowCountRef = React.useRef(0)
  const messagesScrollRef = React.useRef<HTMLDivElement>(null)
  const prevThreadKeyRef = React.useRef<string | undefined>(undefined)
  const prevCommentCountRef = React.useRef(0)

  React.useLayoutEffect(() => {
    const el = workflowScrollRef.current
    const keyChanged = commentThreadKey !== prevWorkflowThreadKeyRef.current
    if (keyChanged) {
      prevWorkflowThreadKeyRef.current = commentThreadKey
      prevWorkflowCountRef.current = 0
    }
    if (!el || workflowItemCount <= 0) {
      prevWorkflowCountRef.current = workflowItemCount
      return
    }
    const grew = workflowItemCount > prevWorkflowCountRef.current
    const initialThread = prevWorkflowCountRef.current === 0 && workflowItemCount > 0
    if (keyChanged || grew || initialThread) {
      el.scrollTop = el.scrollHeight
    }
    prevWorkflowCountRef.current = workflowItemCount
  }, [commentThreadKey, workflowItemCount])

  React.useLayoutEffect(() => {
    const el = messagesScrollRef.current
    const keyChanged = commentThreadKey !== prevThreadKeyRef.current
    if (keyChanged) {
      prevThreadKeyRef.current = commentThreadKey
      prevCommentCountRef.current = 0
    }
    if (!el || effectiveCommentCount <= 0) {
      prevCommentCountRef.current = effectiveCommentCount
      return
    }
    const grew = effectiveCommentCount > prevCommentCountRef.current
    const initialThread = prevCommentCountRef.current === 0 && effectiveCommentCount > 0
    if (keyChanged || grew || initialThread) {
      el.scrollTop = el.scrollHeight
    }
    prevCommentCountRef.current = effectiveCommentCount
  }, [commentThreadKey, effectiveCommentCount, commentGroups])

  const [inputText, setInputText] = React.useState("")
  const [mentionOpen, setMentionOpen] = React.useState(false)
  const [mentionHighlight, setMentionHighlight] = React.useState(0)
  const [explicitMentionIds, setExplicitMentionIds] = React.useState<Set<string>>(new Set())
  const inputRef = React.useRef<HTMLInputElement>(null)
  const caretRef = React.useRef<number | null>(null)

  // Grow the comments card as comments are added, while keeping a sensible cap.
  const commentsCardHeight = Math.min(640, Math.max(220, 220 + effectiveCommentCount * 58))

  const getActiveMentionQuery = React.useCallback((text: string, caret: number) => {
    const before = text.slice(0, caret)
    const at = before.lastIndexOf("@")
    if (at === -1) return null
    const afterAt = before.slice(at + 1)
    if (afterAt.includes(" ") || afterAt.includes("\n")) return null
    return { start: at, query: afterAt }
  }, [])

  const filteredMentionUsers = React.useMemo(() => {
    if (!mentionUsers?.length || !mentionOpen) return []
    // caretRef is set by handleAtButtonClick before state updates so we get the
    // correct position even before requestAnimationFrame fires.
    const caret = caretRef.current ?? inputRef.current?.selectionStart ?? inputText.length
    caretRef.current = null // consume it
    const mq = getActiveMentionQuery(inputText, caret)
    if (!mq) return []
    const q = mq.query.toLowerCase()
    return mentionUsers
      .filter((u) => u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q))
      .slice(0, 8)
  }, [mentionUsers, mentionOpen, inputText, getActiveMentionQuery])

  React.useEffect(() => {
    setMentionHighlight(0)
  }, [filteredMentionUsers.length, mentionOpen])

  const insertMention = React.useCallback(
    (user: MentionUser) => {
      const el = inputRef.current
      const caret = el?.selectionStart ?? inputText.length
      const mq = getActiveMentionQuery(inputText, caret)
      let next: string
      if (mq) {
        const before = inputText.slice(0, mq.start)
        const after = inputText.slice(caret)
        next = `${before}@${user.name} ${after}`
      } else {
        next = `${inputText.replace(/\s*$/, "")} @${user.name} `
      }
      setInputText(next)
      setExplicitMentionIds((prev) => {
        const out = new Set(prev)
        out.add(user.id)
        return out
      })
      setMentionOpen(false)
      window.requestAnimationFrame(() => {
        el?.focus()
        const pos = next.length
        el?.setSelectionRange(pos, pos)
      })
    },
    [getActiveMentionQuery, inputText]
  )

  const extractMentionIdsFromText = React.useCallback(
    (text: string): string[] => {
      if (!mentionUsers?.length) return []
      const ids = new Set<string>()
      const t = text.toLowerCase()
      mentionUsers.forEach((u) => {
        if (t.includes(`@${u.name.toLowerCase()}`)) {
          ids.add(u.id)
        }
      })
      return [...ids]
    },
    [mentionUsers]
  )

  const handleInlineSend = React.useCallback(() => {
    const trimmed = inputText.trim()
    if (!trimmed) return
    const parsedIds = mentionUsers?.length ? extractMentionIdsFromText(trimmed) : undefined
    const ids = new Set<string>(parsedIds || [])
    
    if (mentionUsers?.length) {
      const t = trimmed.toLowerCase()
      explicitMentionIds.forEach((id) => {
        const u = mentionUsers.find((user) => user.id === id)
        if (u && (t.includes(`@${u.name.toLowerCase()}`) || t.includes(`@${u.email.toLowerCase()}`))) {
          ids.add(id)
        }
      })
    } else {
      explicitMentionIds.forEach((id) => ids.add(id))
    }
    
    const finalIds = [...ids]
    onSendComment?.(trimmed, finalIds.length ? finalIds : undefined)
    setInputText("")
    setExplicitMentionIds(new Set())
    setMentionOpen(false)
  }, [explicitMentionIds, extractMentionIdsFromText, inputText, mentionUsers, onSendComment])

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setInputText(v)
    const caret = e.target.selectionStart ?? v.length
    const mq = getActiveMentionQuery(v, caret)
    setMentionOpen(!!(mq && mentionUsers?.length))
  }

  const handleAtButtonClick = () => {
    const el = inputRef.current
    if (!el) return
    const caret = el.selectionStart ?? inputText.length
    const before = inputText.slice(0, caret)
    const after = inputText.slice(caret)
    const nextText = before.endsWith("@") ? inputText : `${before}@${after}`
    const newCaret = before.endsWith("@") ? caret : caret + 1
    // Store newCaret BEFORE state updates so filteredMentionUsers memo can
    // use it (inputRef.current.selectionStart is stale until after rAF)
    caretRef.current = newCaret
    setInputText(nextText)
    if (mentionUsers?.length) {
      setMentionOpen(true)
    }
    window.requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(newCaret, newCaret)
    })
  }

  const onInputSelect = () => {
    const el = inputRef.current
    if (!el) return
    const mq = getActiveMentionQuery(inputText, el.selectionStart ?? 0)
    setMentionOpen(!!(mq && mentionUsers?.length))
  }

  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (mentionOpen && filteredMentionUsers.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault()
        setMentionHighlight((h) => (h + 1) % filteredMentionUsers.length)
        return
      }
      if (e.key === "ArrowUp") {
        e.preventDefault()
        setMentionHighlight((h) => (h - 1 + filteredMentionUsers.length) % filteredMentionUsers.length)
        return
      }
      if (e.key === "Enter") {
        e.preventDefault()
        insertMention(filteredMentionUsers[mentionHighlight])
        return
      }
      if (e.key === "Escape") {
        setMentionOpen(false)
        return
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleInlineSend()
    }
  }

  return (
    <div className={cn("h-full rounded-xl border bg-card flex flex-col", className)}>

      {/* ══ APPROVAL WORKFLOW section ══ */}
      <div className="flex min-h-0 shrink-0 max-h-[45%] flex-col">
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-sm font-semibold text-foreground">Approval Workflow</span>
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
          ) : (
            <span className="h-6 w-6 shrink-0" aria-hidden />
          )}
        </div>

        {/* Timeline */}
        <div
          ref={workflowScrollRef}
          className="activity-scroll relative min-h-0 flex-1 overflow-y-auto px-8 pb-3 pr-2"
        >
          <div className="space-y-2">
            {workflowGroups.map((group, groupIdx) => (
              <div key={group.versionLabel} className="relative pl-0">
                {/* Line segment above version header */}
                {groupIdx === 0 ? (
                  <div className="pointer-events-none absolute left-[18px] top-0 h-2 w-px bg-foreground/10" />
                ) : (
                  <div className="pointer-events-none absolute left-[18px] -top-2 h-2 w-px bg-foreground/10" />
                )}

                {/* Version Header — centered on line, creates hole, sticky */}
                <div className="sticky top-0 z-20 mb-2 flex bg-card/95 py-1 backdrop-blur-md">
                  <div className="flex min-w-[36px] shrink-0 basis-[36px] justify-center bg-card">
                    <span className="whitespace-nowrap px-2 py-0.5 text-[11px] font-semibold text-primary">
                      {group.versionLabel}
                    </span>
                  </div>
                </div>

                {/* Line segment below date */}
                <div
                  className="pointer-events-none absolute left-[18px] w-px bg-foreground/10"
                  style={{ top: 22, bottom: -6 }}
                />

                <div className="space-y-4">
                  {group.items.map((item, idx) => {
                    const isApproved = item.title === "Approved"
                    // Pre-computed solid colors: each Figma opacity blended over white
                    // info:    #5BC0EB @10% → #EFF9FD
                    // warning: #F1C21B @10% → #FEF9E8
                    // danger:  #FF832B @10% → #FFF3EA
                    // success: #24A148 @10% → #E9F6ED
                    const kindBgColor: Record<WorkflowKind, string> = {
                      info: "bg-[#EFF9FD] dark:bg-[#1e3a5f]/90",
                      warning: "bg-[#FEF9E8] dark:bg-amber-950/80",
                      danger: "bg-[#FFF3EA] dark:bg-red-950/80",
                      success: "bg-[#E9F6ED] dark:bg-emerald-950/80",
                    }
                    return (
                      /* Row: [icon on line] [gap] [speech bubble card] */
                      <div key={idx} className="flex items-start gap-3">
                        {/* Icon column — fixed width, icon centered on line */}
                        <div className="relative z-10 flex min-w-[36px] shrink-0 basis-[36px] justify-center">
                          <WorkflowIcon kind={item.kind} />
                        </div>

                        {/* Card with notch */}
                        <div className="relative min-w-0 flex-1">
                          {/* Left arrow notch — rotated square with rounded tip, solid color matches card */}
                          <div
                            className={cn(
                              "absolute left-0 top-[24%] z-0 h-3 w-3 -translate-x-1/2 rotate-45 rounded-[3px]",
                              kindBgColor[item.kind],
                            )}
                          />
                          <div
                            role={isApproved ? "button" : undefined}
                            tabIndex={isApproved ? 0 : undefined}
                            onClick={isApproved ? onApprovedClick : undefined}
                            onKeyDown={isApproved ? (e) => e.key === "Enter" && onApprovedClick?.() : undefined}
                            className={cn(
                              "relative z-10 min-w-0 rounded-lg pl-3 pr-2.5 py-1.5 shadow-[0_1px_2px_rgba(16,24,40,0.06)] dark:shadow-[0_1px_6px_rgba(255,255,255,0.08)]",
                              isApproved && "cursor-pointer",
                              kindBgColor[item.kind],
                            )}
                          >
                            <div className="relative">
                              <div className="flex items-center justify-between gap-2">
                                <span className="truncate text-xs font-semibold text-foreground">{item.title}</span>
                                <span className="shrink-0 rounded-md bg-card dark:bg-muted px-2 py-0.5 text-[10px] font-medium text-foreground/80">
                                  {item.stage}
                                </span>
                              </div>
                              <div className="mt-0.5 flex items-center justify-between gap-1.5">
                                <div className="flex items-center gap-1.5">
                                  <Avatar name={item.user} size={16} />
                                  <span className="truncate text-[11px] text-muted-foreground">{item.user}</span>
                                </div>
                                <div className="flex shrink-0 items-center gap-1.5">
                                  <Clock className="h-3 w-3 text-muted-foreground" />
                                  <span className="text-[10px] text-muted-foreground">{item.time}</span>
                                </div>
                              </div>
                              {item.comment ? (
                                <div className="mt-2 rounded-md bg-card/60 dark:bg-muted/60 px-2 py-1.5">
                                  <p className="text-[11px] leading-4 text-muted-foreground">{item.comment}</p>
                                </div>
                              ) : null}
                            </div>
                          </div>
                        </div>{/* end notch wrapper */}
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ══ COMMENTS & DISCUSSION section ══ */}
      {showComments ? (
        <div className="flex flex-1 min-h-0 flex-col pt-7">
          {/* Title — outside card */}
          <div className="flex shrink-0 items-center justify-between gap-2 px-4 pb-3 pt-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground">
                Comments &amp; Discussion
              </span>
              <span className="text-xs text-muted-foreground">({effectiveCommentCount})</span>
            </div>
            {onCommentsExpandToggle && (
              <button
                type="button"
                onClick={onCommentsExpandToggle}
                className="inline-flex items-center gap-1.5 rounded-md border border-foreground/15 bg-card px-2 py-0.5 text-[10px] font-medium text-foreground shadow-sm transition-colors hover:bg-accent"
                aria-label={commentsExpanded ? "Collapse comments panel" : "Expand comments panel"}
              >
                {commentsExpanded ? (
                  <Minimize2 className="h-3 w-3" />
                ) : (
                  <Maximize2 className="h-3 w-3" />
                )}
                <span className="text-[10px]">{commentsExpanded ? "Collapse" : "Expand"}</span>
              </button>
            )}
          </div>

          {/* Card: messages (scroll) + compact footer */}
          {!commentsExpanded ? (
            <div
              className="mx-5 mb-5 flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg bg-muted border border-foreground/5 shadow-inner"
            >
              {/* Messages — scrollable area (default scroll = bottom / latest comments) */}
              <div
                ref={messagesScrollRef}
                className="activity-scroll min-h-0 flex-1 overflow-y-auto px-4 pb-3 pt-0"
              >
                <div className="space-y-3">
                  {commentGroups.map((group) => (
                    <div key={group.versionLabel} className="relative space-y-2">
                      <div className="sticky top-0 z-10 -mx-4 flex items-center justify-center bg-muted px-4 py-2.5 border-b border-foreground/10 shadow-sm">
                        <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-primary bg-primary/10 px-2.5 py-0.5 rounded-full uppercase tracking-wider">
                          Version {group.versionLabel}
                        </span>
                      </div>

                      {group.items.map((c, idx) => (
                        <div
                          key={idx}
                          className={cn(
                            "rounded-xl border border-foreground/10 bg-card px-4 py-3 shadow-[0_1px_2px_rgba(16,24,40,0.06)] dark:shadow-[0_1px_2px_rgba(0,0,0,0.2)]",
                            "transition-colors"
                          )}
                        >
                          <div className="mb-1 flex flex-wrap items-center gap-2 overflow-hidden">
                            <Avatar name={c.user} size={20} />
                            <span className="shrink-0 text-xs font-semibold text-foreground">{c.user}</span>
                            {c.tag && (
                              <div className="flex flex-wrap gap-1">
                                {c.tag.substring(1).split(", ").map(t => (
                                  <span key={t} className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium", getRoleBadgeClasses(t))}>
                                    {t}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground break-words">{renderCommentText(c.text)}</p>
                          <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                            <Clock className="h-2.5 w-2.5 shrink-0" />
                            {c.time}
                          </div>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </div>

              {/* Inline composer */}
              <div className="relative shrink-0 border-t border-foreground/5 bg-muted/50 px-3 py-2">
                {disabled ? (
                  <div className="flex h-11 items-center gap-2 rounded-full border border-dashed border-muted-foreground/30 bg-[#F7F8F9] px-4">
                    <svg
                      className="h-4 w-4 shrink-0 text-muted-foreground/50"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                      />
                    </svg>
                    <span className="flex-1 select-none text-sm text-muted-foreground/60">{disabledMessage}</span>
                  </div>
                ) : (
                  <>
                    {mentionOpen && filteredMentionUsers.length > 0 ? (
                      <div
                        className="absolute bottom-full left-3 right-3 z-20 mb-1 max-h-48 overflow-y-auto rounded-lg border bg-popover py-1 shadow-md"
                        role="listbox"
                      >
                        {filteredMentionUsers.map((u, i) => (
                          <button
                            key={u.id}
                            type="button"
                            role="option"
                            className={cn(
                              "flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-accent",
                              i === mentionHighlight && "bg-accent"
                            )}
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => insertMention(u)}
                          >
                            <span className="font-medium text-foreground">{u.name}</span>
                            <span className="text-xs text-muted-foreground">{u.email}</span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <div className="flex h-11 items-center gap-2 rounded-full bg-[#F7F8F9] pl-4 pr-1.5">
                      <button
                        type="button"
                        onClick={handleAtButtonClick}
                        className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-black/5 transition-colors"
                        title="Mention someone (@)"
                        aria-label="Mention someone"
                      >
                        <img src="/documents/At.svg" alt="@" className="h-4 w-4 shrink-0" />
                      </button>
                      <input
                        ref={inputRef}
                        value={inputText}
                        onChange={onInputChange}
                        onKeyDown={onInputKeyDown}
                        onSelect={onInputSelect}
                        onClick={onInputSelect}
                        placeholder="Add a comment... Use @ to tag someone by name or email"
                        className="h-auto min-h-0 flex-1 border-0 bg-transparent px-2 py-0 text-sm text-[#1C1C1C] caret-[#1C1C1C] outline-none placeholder:text-muted-foreground dark:text-[#1C1C1C] dark:caret-[#1C1C1C]"
                      />
                      <button
                        type="button"
                        onClick={handleInlineSend}
                        className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#128BDA] text-white hover:bg-[#128BDA]/90"
                        aria-label="Send comment"
                      >
                        <img
                          src="/shared/PaperPlaneTilt.svg"
                          alt="Send"
                          className="h-3.5 w-3.5"
                          style={{ filter: "brightness(0) invert(1)" }}
                        />
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="mx-5 mb-5 rounded-lg border border-dashed border-foreground/15 bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
              Expanded comments view is open.
            </div>
          )}
        </div>
      ) : null}

    </div>
  )
}