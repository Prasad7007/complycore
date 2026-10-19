import * as React from "react"
import { cn } from "@/lib/utils"
import { Calendar, Clock, Minimize2 } from "lucide-react"
import { useTheme } from "@/context/theme-context"

export type TaggableUser = {
  id: string
  label: string
  person?: string
  assigned: boolean
  tag: string
}

export type CommentItem = {
  user: string
  tag?: string
  text: string
  time: string
  changeRequest?: boolean
  isSent?: boolean
}

export type CommentGroup = {
  versionLabel: string
  items: CommentItem[]
}

const defaultUsers: TaggableUser[] = [
  { id: "marketing", label: "Marketing Reviewer", person: "John Smith", assigned: true, tag: "@Marketing" },
  { id: "sme", label: "SME", person: "Dr. James Chen", assigned: true, tag: "@SME" },
  { id: "admin", label: "Admin", assigned: false, tag: "@Admin" },
  { id: "compliance", label: "Compliance", assigned: false, tag: "@Compliance" },
]

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

export type MentionUser = {
  id: string
  email: string
  name: string
}

function extractMentionIdsFromText(text: string, users: MentionUser[]): string[] {
  if (!users.length) return []
  const ids = new Set<string>()
  const t = text.toLowerCase()
  users.forEach((u) => {
    if (t.includes(`@${u.name.toLowerCase()}`)) {
      ids.add(u.id)
    }
  })
  const uuidRe =
    /@([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/gi
  let m: RegExpExecArray | null
  while ((m = uuidRe.exec(t)) !== null) {
    if (users.some((u) => u.id === m[1])) ids.add(m[1])
  }
  return [...ids]
}

/** Strips the leading @ from any @mention in comment body text for display. */
function renderCommentText(text: string): string {
  return text.replace(/@(\S+)/g, "$1")
}

function getActiveMentionQuery(
  text: string,
  caret: number
): { start: number; query: string } | null {
  const before = text.slice(0, caret)
  const at = before.lastIndexOf("@")
  if (at === -1) return null
  const afterAt = before.slice(at + 1)
  if (afterAt.includes(" ") || afterAt.includes("\n")) return null
  return { start: at, query: afterAt }
}

export type CommentTrailProps = {
  users?: TaggableUser[]
  /** When set, chips and @ autocomplete use real users; mentions use @email in text. */
  mentionUsers?: MentionUser[]
  commentGroups?: CommentGroup[]
  className?: string
  onSendComment?: (text: string, mentionedUserIds?: string[]) => void
  /** When true, the comment input is locked and the user is shown a claim-first message. */
  disabled?: boolean
  disabledMessage?: string
  showCollapseToggle?: boolean
  onCollapseToggle?: () => void
  /** When this value changes (e.g. document id), comment list scroll anchor resets. */
  commentThreadKey?: string
}

// Role-based message background colors
const roleBgColor: Record<string, string> = {
  "@Marketing": "#E9F6ED",   // green tint
  "@SME":        "#EFF9FD",  // sky blue tint
  "@Compliance": "#FEF9E8",  // yellow tint
  "@Admin":      "#E8F4FC",  // light blue tint
  "@Super Admin": "#E8F4FC",
  "@AI":         "#FFF3EA",
  "@Profile":    "#FFF3EA",  // orange tint
}

const roleBgColorDark: Record<string, string> = {
  "@Marketing": "#123220",
  "@SME": "#153049",
  "@Compliance": "#3a2f11",
  "@Admin": "#0d2a3d",
  "@Super Admin": "#0d2a3d",
  "@AI": "#3d2314",
  "@Profile": "#3d2314",
}

const roleBadgeBg: Record<string, string> = {
  "@Marketing": "#24A148",
  "@SME":        "#5BC0EB",
  "@Compliance": "#F1C21B",
  "@Admin":      "#128BDA",
  "@Super Admin": "#128BDA",
  "@AI":         "#FF832B",
  "@Profile":    "#FF832B",
}

function getTodayDate() {
  const d = new Date()
  return `${String(d.getDate()).padStart(2,"0")}-${String(d.getMonth()+1).padStart(2,"0")}-${d.getFullYear()}`
}
function getNowTime() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`
}

export function CommentTrail({
  users = defaultUsers,
  mentionUsers,
  commentGroups = [],
  className,
  onSendComment,
  disabled = false,
  disabledMessage = "Claim the review to add comments",
  showCollapseToggle = false,
  onCollapseToggle,
  commentThreadKey = "",
}: CommentTrailProps) {
  const [selectedTag, setSelectedTag] = React.useState<string | null>(null)
  const [inputText, setInputText] = React.useState("")
  const [localGroups, setLocalGroups] = React.useState<CommentGroup[]>(commentGroups)
  const inputRef = React.useRef<HTMLInputElement>(null)
  const [mentionOpen, setMentionOpen] = React.useState(false)
  const [mentionHighlight, setMentionHighlight] = React.useState(0)
  const [explicitMentionIds, setExplicitMentionIds] = React.useState<Set<string>>(new Set())
  const { theme } = useTheme()
  const isDarkTheme = theme === "dark"

  const chipUsers: TaggableUser[] = React.useMemo(() => {
    if (mentionUsers?.length) {
      return mentionUsers.map((u) => ({
        id: u.id,
        label: u.name,
        person: u.email,
        assigned: true,
        tag: `@${u.email}`,
      }))
    }
    return users
  }, [mentionUsers, users])

  React.useEffect(() => {
    setLocalGroups(commentGroups)
  }, [commentGroups])

  const hasComments = localGroups.some((g) => g.items.length > 0)

  const filteredGroups = React.useMemo(() => {
    return localGroups.filter((g) => g.items.length > 0)
  }, [localGroups])

  const filteredCommentTotal = React.useMemo(
    () => filteredGroups.reduce((sum, g) => sum + g.items.length, 0),
    [filteredGroups]
  )

  const messagesScrollRef = React.useRef<HTMLDivElement>(null)
  const prevThreadKeyRef = React.useRef<string | undefined>(undefined)
  const prevCommentCountRef = React.useRef(0)

  React.useLayoutEffect(() => {
    const el = messagesScrollRef.current
    const keyChanged = commentThreadKey !== prevThreadKeyRef.current
    if (keyChanged) {
      prevThreadKeyRef.current = commentThreadKey
      prevCommentCountRef.current = 0
    }
    if (!el || filteredCommentTotal <= 0) {
      prevCommentCountRef.current = filteredCommentTotal
      return
    }
    const grew = filteredCommentTotal > prevCommentCountRef.current
    const initialThread = prevCommentCountRef.current === 0 && filteredCommentTotal > 0
    if (keyChanged || grew || initialThread) {
      el.scrollTop = el.scrollHeight
    }
    prevCommentCountRef.current = filteredCommentTotal
  }, [commentThreadKey, filteredCommentTotal, filteredGroups])

  const showCommentsView = hasComments

  const filteredMentionUsers = React.useMemo(() => {
    if (!mentionUsers?.length || !mentionOpen) return []
    const caret = inputRef.current?.selectionStart ?? inputText.length
    const mq = getActiveMentionQuery(inputText, caret)
    if (!mq) return []
    const q = mq.query.toLowerCase()
    return mentionUsers.filter(
      (u) =>
        u.name.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q)
    ).slice(0, 8)
  }, [mentionUsers, mentionOpen, inputText])

  React.useEffect(() => {
    setMentionHighlight(0)
  }, [filteredMentionUsers.length, mentionOpen])

  const insertMention = (user: MentionUser) => {
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
  }

  const handleSend = () => {
    const trimmed = inputText.trim()
    if (!trimmed) return
    const parsedIds = mentionUsers?.length
      ? extractMentionIdsFromText(trimmed, mentionUsers)
      : undefined
    const ids = new Set<string>(parsedIds || [])
    
    if (mentionUsers?.length) {
      const t = trimmed.toLowerCase()
      explicitMentionIds.forEach((id) => {
        const u = mentionUsers.find(user => user.id === id)
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
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (mentionOpen && filteredMentionUsers.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault()
        setMentionHighlight((h) => (h + 1) % filteredMentionUsers.length)
        return
      }
      if (e.key === "ArrowUp") {
        e.preventDefault()
        setMentionHighlight(
          (h) => (h - 1 + filteredMentionUsers.length) % filteredMentionUsers.length
        )
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
      handleSend()
    }
  }

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setInputText(v)
    const caret = e.target.selectionStart ?? v.length
    const mq = getActiveMentionQuery(v, caret)
    setMentionOpen(!!(mq && mentionUsers?.length))
  }

  const onInputSelect = () => {
    const el = inputRef.current
    if (!el) return
    const mq = getActiveMentionQuery(inputText, el.selectionStart ?? 0)
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

    setInputText(nextText)
    if (mentionUsers?.length) {
      setMentionOpen(true)
    }

    window.requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(newCaret, newCaret)
    })
  }

  return (
    <div
      className={cn("flex flex-col rounded-xl border bg-card overflow-hidden h-full", className)}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-5 py-4">
        <div className="flex items-center gap-2">
          <img src="/shared/chatIcon.svg" alt="" className="h-5 w-5" />
          <span className="text-sm font-semibold text-foreground">Comment Trail</span>
        </div>
        {showCollapseToggle ? (
          <button
            type="button"
            onClick={onCollapseToggle}
            className="inline-flex items-center gap-1.5 rounded-md border border-foreground/15 bg-card px-2.5 py-1 text-[11px] font-medium text-foreground shadow-sm hover:bg-accent"
            aria-label="Collapse comments panel"
          >
            <Minimize2 className="h-3.5 w-3.5" />
            Collapse
          </button>
        ) : null}
      </div>

      {/* Main content — welcome or messages */}
      {showCommentsView ? (
        <div className="flex flex-1 min-h-0 flex-col">
          {/* Scrollable messages only (default scroll = bottom / latest comments) */}
          <div
            ref={messagesScrollRef}
            className="flex-1 min-h-0 overflow-y-auto px-4 sm:px-6 xl:px-12 2xl:px-20 py-3"
          >
          <div className="space-y-3">
            {filteredGroups.map((group) => (
              <div key={group.versionLabel} className="space-y-2 relative">
                <div className="sticky top-0 z-10 flex items-center justify-center py-4 pointer-events-none">
                  <div className="rounded-full bg-primary/10 backdrop-blur-xl px-5 py-2 text-[13px] font-bold text-primary shadow-lg ring-2 ring-primary/20 border border-white/20">
                    <div className="flex items-center gap-2 uppercase tracking-wider">
                      Version {group.versionLabel}
                    </div>
                  </div>
                </div>
                {group.items.map((c, idx) => {
                  // Change request — avatar outside left, full-width card
                  if (c.changeRequest) {
                    return (
                      <div key={idx} className="flex items-start gap-3">
                        <div className="flex flex-col items-center gap-1 shrink-0">
                          <Avatar name={c.user} size={28} />
                          <span className="text-[9px] text-muted-foreground text-center leading-tight max-w-[40px] truncate">{c.user.split(" ")[0]}</span>
                        </div>
                        <div className="flex-1 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5">
                          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                            <span className="rounded-md bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-600">
                              Change Requested by SME
                            </span>
                            {c.tag && (
                              <div className="flex flex-wrap gap-1">
                                {c.tag.substring(1).split(", ").map(t => {
                                  const tagStr = `@${t}`
                                  return (
                                    <span key={tagStr} className="rounded-full bg-[#E5E7EB] px-2 py-0.5 text-[10px] font-medium text-foreground">
                                      {t}
                                    </span>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground">{renderCommentText(c.text)}</p>
                          <div className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                            <Clock className="h-2.5 w-2.5" />
                            {c.time}
                          </div>
                        </div>
                      </div>
                    )
                  }
                  const primaryTag = c.tag ? `@${c.tag.substring(1).split(", ")[0]}` : ""
                  const msgBg = isDarkTheme
                    ? roleBgColorDark[primaryTag] ?? "hsl(var(--muted))"
                    : roleBgColor[primaryTag] ?? "hsl(var(--muted))"

                  // Sent message — right-aligned
                  if (c.isSent) {
                    return (
                      <div key={idx} className="flex justify-end">
                        <div className="w-full rounded-xl border border-border px-3 py-2.5 shadow-[0_1px_3px_rgba(16,24,40,0.06)]" style={{ backgroundColor: msgBg }}>
                          <div className="mb-1.5 flex flex-wrap items-center gap-2 overflow-hidden">
                            <span className="shrink-0 text-xs font-semibold text-foreground">{c.user}</span>
                            {c.tag && (
                              <div className="flex flex-wrap gap-1">
                                {c.tag.substring(1).split(", ").map(t => {
                                  const tagStr = `@${t}`
                                  return (
                                    <span key={tagStr} className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium text-white" style={{ backgroundColor: roleBadgeBg[tagStr] || "#6B7280" }}>
                                      {t}
                                    </span>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground break-words">{renderCommentText(c.text)}</p>
                          <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                            <Clock className="h-2.5 w-2.5 shrink-0" />
                            {c.time}
                          </div>
                        </div>
                      </div>
                    )
                  }
                  // Received message — left-aligned with avatar in header
                  return (
                    <div key={idx} className="w-full rounded-xl border border-border px-3 py-2.5 shadow-[0_1px_3px_rgba(16,24,40,0.06)]" style={{ backgroundColor: msgBg }}>
                      <div className="mb-1.5 flex flex-wrap items-center gap-2 overflow-hidden">
                        <Avatar name={c.user} size={20} />
                        <span className="shrink-0 text-xs font-semibold text-foreground">{c.user}</span>
                        {c.tag && (
                          <div className="flex flex-wrap gap-1">
                            {c.tag.substring(1).split(", ").map(t => {
                              const tagStr = `@${t}`
                              return (
                                <span key={tagStr} className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium text-white" style={{ backgroundColor: roleBadgeBg[tagStr] || "#6B7280" }}>
                                  {t}
                                </span>
                              )
                            })}
                          </div>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground break-words">{renderCommentText(c.text)}</p>
                      <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                        <Clock className="h-2.5 w-2.5 shrink-0" />
                        {c.time}
                      </div>
                    </div>
                  )
                })}
              </div>
            ))}
          </div>

          </div>{/* end scrollable messages */}
        </div>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-16">
          <div className="w-full max-w-[460px] text-center">
            <h2 className="text-4xl font-semibold text-foreground">
              Welcome to Comment Trail
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Tag the one to whom you want to message and start comment trail
            </p>
          </div>
        </div>
      )}

      {/* Comment input */}
      <div className="relative shrink-0 px-4 py-3">
        {disabled ? (
          <div className="flex h-12 items-center gap-2 rounded-full bg-muted px-4 border border-dashed border-muted-foreground/30 cursor-not-allowed">
            <svg className="h-4 w-4 shrink-0 text-muted-foreground/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
            <span className="flex-1 text-sm text-muted-foreground/60 select-none">{disabledMessage}</span>
          </div>
        ) : (
          <>
            {mentionOpen && filteredMentionUsers.length > 0 ? (
              <div
                className="absolute bottom-full left-4 right-4 z-20 mb-1 max-h-48 overflow-y-auto rounded-lg border bg-popover py-1 shadow-md"
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
            <div className="flex h-12 items-center gap-2 rounded-full bg-muted pl-4 pr-1.5">
              <button
                type="button"
                onClick={handleAtButtonClick}
                className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                title="Mention someone (@)"
                aria-label="Mention someone"
              >
                <img src="/documents/At.svg" alt="@" className="h-4 w-4 shrink-0" />
              </button>
              <input
                ref={inputRef}
                value={inputText}
                onChange={onInputChange}
                onKeyDown={handleKeyDown}
                onSelect={onInputSelect}
                onClick={onInputSelect}
                placeholder="Add a comment... Use @ to tag someone by name or email"
                className="h-auto min-h-0 flex-1 border-0 bg-transparent px-2 py-0 text-sm text-foreground caret-foreground outline-none placeholder:text-muted-foreground"
              />
              <button
                type="button"
                onClick={handleSend}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#128BDA] text-white hover:bg-[#128BDA]/90"
                aria-label="Send comment"
              >
                <img src="/shared/PaperPlaneTilt.svg" alt="Send" className="h-4 w-4" style={{ filter: "brightness(0) invert(1)" }} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
