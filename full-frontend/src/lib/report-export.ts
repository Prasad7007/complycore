import type { ComplianceReportRow } from "@/lib/api"
import { LOGO_HEX, LOGO_WIDTH, LOGO_HEIGHT } from "./logo-data"

export type ComplianceFinding = {
  title?: string
  risk_level?: string
  status?: string
  description?: string
  why_risky?: string
  rationale?: string
  ai_suggestion?: string
  accepted_suggestion_text?: string
}

export type AuditTrailEvent = {
  id?: string
  event_type?: string
  timestamp?: string
  time?: string
  date?: string
  user?: string
  user_role?: string
  is_ai?: boolean
  description?: string
  details?: string | null
  comment?: string | null
  finding?: { title?: string; risk_level?: string } | null
  workflow_stage?: string
  previous_stage?: string | null
}

const AUDIT_EVENT_LABELS: Record<string, string> = {
  uploaded: "Document Uploaded",
  reuploaded: "Document Re-uploaded",
  claim: "Review Claimed",
  approve: "Approved",
  sme_approve: "SME Approved",
  submit_to_compliance: "Sent to Compliance",
  approve_and_lock: "Approved & Locked",
  reject: "Rejected",
  request_changes: "Changes Requested",
  finding_accepted: "AI Finding Accepted",
  finding_rejected: "AI Finding Rejected",
  finding_comment_added: "Comment on Finding",
  finding_suggestion_added: "Alternate Suggestion",
  comment_added: "Comment Added",
  ai_analysis_started: "AI Analysis Started",
  ai_analysis_completed: "AI Analysis Completed",
  ai_analysis_skipped: "AI Analysis Skipped",
  ai_analysis_failed: "AI Analysis Failed",
  workflow_stage_changed: "Stage Changed",
  review_claimed: "Review Claimed",
  review_completed: "Review Completed",
  changes_requested: "Changes Requested",
  document_locked: "Document Locked",
}

export function formatAuditEventLabel(event_type?: string): string {
  if (!event_type) return "Event"
  return AUDIT_EVENT_LABELS[event_type] || event_type.replace(/_/g, " ")
}

export function formatReportDate(isoStr: string, includeTime = true) {
  if (!isoStr) return ""
  const d = new Date(isoStr)
  if (isNaN(d.getTime())) return isoStr
  return includeTime
    ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
    : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function sanitizeAscii(input: string) {
  return String(input || "").replace(/[^\x20-\x7E]/g, " ")
}

function escapePdfText(input: string) {
  return sanitizeAscii(input)
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)")
}

function wrapText(input: string, maxChars: number): string[] {
  const text = sanitizeAscii(input).trim()
  if (!text) return [""]

  const words = text.split(/\s+/)
  const lines: string[] = []
  let current = ""

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word
    if (candidate.length <= maxChars) {
      current = candidate
      continue
    }
    if (current) lines.push(current)
    current = word
  }

  if (current) lines.push(current)
  return lines
}

function clampText(input: string, maxLen = 500): string {
  const text = sanitizeAscii(input || "")
  if (text.length <= maxLen) return text
  return `${text.slice(0, maxLen - 3)}...`
}

/** Human-readable workflow stage names for exports (matches UI where applicable). */
const WORKFLOW_STAGE_LABELS: Record<string, string> = {
  sme_review: "SME Review",
  marketing_review: "Marketing Review",
  compliance_review: "Compliance Review",
  needs_revision: "Needs Revision",
  publish: "Approved",
  approved: "Approved",
  published: "Published",
  rejected: "Rejected",
  document_upload: "Upload",
}

function formatStageLabelForExport(stage?: string | null): string {
  if (!stage) return ""
  return WORKFLOW_STAGE_LABELS[stage] || stage.replace(/_/g, " ")
}

function formatJsonValueForReadable(value: unknown, depth: number): string {
  const pad = "  ".repeat(depth)
  if (value === null) return "null"
  if (value === undefined) return "—"
  if (typeof value === "string") {
    const t = sanitizeAscii(value)
    if (t.length <= 88) return t
    const chunks: string[] = []
    for (let i = 0; i < t.length; i += 88) chunks.push(t.slice(i, i + 88))
    return chunks.join("\n")
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  if (Array.isArray(value)) {
    if (value.length === 0) return "(empty)"
    return value
      .map((item, i) => {
        const inner = formatJsonValueForReadable(item, depth + 1)
        if (inner.includes("\n")) {
          return `${pad}• ${i + 1}\n${inner}`
        }
        return `${pad}• ${inner}`
      })
      .join("\n")
  }
  if (typeof value === "object") {
    const o = value as Record<string, unknown>
    const technicalKeys = ["finding_id", "finding_uuid", "comment_id", "suggestion_id", "user_id"]
    return Object.entries(o)
      .filter(([k]) => !technicalKeys.includes(k.toLowerCase()))
      .map(([k, val]) => {
        const label = k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
        const inner = formatJsonValueForReadable(val, depth + 1)
        if (val !== null && typeof val === "object") {
          return `${pad}${label}:\n${inner}`
        }
        return `${pad}${label}: ${inner}`
      })
      .join("\n")
  }
  return sanitizeAscii(String(value))
}

/** Turns JSON-looking strings (and nested objects) into plain-language lines for PDF/TXT. */
function formatAuditDetailTextForExport(raw: string): string {
  const s = String(raw ?? "").trim()
  if (!s) return ""
  const looksJson =
    (s.startsWith("{") && s.endsWith("}")) || (s.startsWith("[") && s.endsWith("]"))
  if (looksJson) {
    try {
      const parsed = JSON.parse(s) as unknown
      return formatJsonValueForReadable(parsed, 0)
    } catch {
      return sanitizeAscii(s)
    }
  }
  return sanitizeAscii(s)
}

/** Merges comment / details / description without duplicating identical JSON blobs. */
function buildAuditEventDetailForExport(ev: AuditTrailEvent): string {
  const chunks: string[] = []
  const add = (s: string | null | undefined) => {
    const t = formatAuditDetailTextForExport(String(s ?? ""))
    if (t) chunks.push(t)
  }
  if (ev.comment) add(ev.comment)
  if (ev.details && ev.details !== ev.comment) add(ev.details)
  if (ev.description && ev.description !== ev.comment && ev.description !== ev.details) {
    add(ev.description)
  }
  const seen = new Set<string>()
  const uniq = chunks.filter((c) => {
    const k = c.trim()
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
  let body = uniq.join("\n\n")
  if (ev.finding?.title) {
    const ft = `Related finding: ${ev.finding.title}${
      ev.finding.risk_level ? ` (${String(ev.finding.risk_level)})` : ""
    }`
    if (!body.includes(ev.finding.title)) {
      body = body ? `${body}\n\n${ft}` : ft
    }
  }
  return body.trim()
}

function buildAuditStageLineForExport(ev: AuditTrailEvent): string {
  const a = ev.previous_stage ? formatStageLabelForExport(ev.previous_stage) : ""
  const b = ev.workflow_stage ? formatStageLabelForExport(ev.workflow_stage) : ""
  if (a && b) return `Stage: ${a} → ${b}`
  if (b) return `Stage: ${b}`
  if (a) return `Stage: ${a}`
  return ""
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).length
}

function getReportVersionLabel(report: ComplianceReportRow): string {
  const withOptional = report as ComplianceReportRow & Record<string, unknown>
  const candidates = [
    withOptional.version_label,
    withOptional.document_version,
    withOptional.version,
    withOptional.review_version,
    withOptional.current_version,
  ]

  for (const value of candidates) {
    if (value === null || value === undefined) continue
    if (typeof value === "string" && value.trim()) return value.trim()
    if (typeof value === "number" && Number.isFinite(value)) return String(value)
  }
  return "N/A"
}

function buildReportPdfFileName(report: ComplianceReportRow): string {
  const rawBase = sanitizeAscii(report.document_name || "document").trim().toLowerCase()
  const normalizedBase = rawBase.replace(/\.[a-z0-9]{1,8}$/i, "")
  const safeBase = normalizedBase
    .replace(/[\\/:*?"<>|]+/g, " ")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "")

  return `${safeBase || "document"}_report.pdf`
}

function buildReportTxtFileName(report: ComplianceReportRow): string {
  const rawBase = sanitizeAscii(report.document_name || "document").trim().toLowerCase()
  const normalizedBase = rawBase.replace(/\.[a-z0-9]{1,8}$/i, "")
  const safeBase = normalizedBase
    .replace(/[\\/:*?"<>|]+/g, " ")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "")

  return `${safeBase || "document"}_report.txt`
}

export function buildReportPdfBlob(
  report: ComplianceReportRow,
  findings: ComplianceFinding[],
  auditEvents: AuditTrailEvent[] = []
): Blob {
  // ── Theme ────────────────────────────────────────────────────────────────
  const PRODUCT_BLUE = { r: 0.122, g: 0.306, b: 0.847 } // #1F4ED8
  const DEEP_BLUE    = { r: 0.08,  g: 0.18,  b: 0.45  }
  const TEXT_DARK    = { r: 0.12,  g: 0.12,  b: 0.12  }
  const TEXT_MUTED   = { r: 0.38,  g: 0.40,  b: 0.46  }
  const BORDER_SOFT  = { r: 0.85,  g: 0.89,  b: 0.96  }

  // ── Layout (single source of truth) ─────────────────────────────────────
  const PAGE_W             = 595
  const PAGE_H             = 842
  const MARGIN_X           = 48
  const HEADER_BAR_H       = 54
  const HEADER_BAR_TOP_Y   = PAGE_H - 16                       // 826
  const HEADER_BAR_BOTTOM  = HEADER_BAR_TOP_Y - HEADER_BAR_H   // 772
  const CONTENT_TOP        = HEADER_BAR_BOTTOM - 22            // 750
  const CONTENT_BOTTOM     = 60                                 // footer reservation
  const CARD_X             = 42
  const CARD_W             = PAGE_W - CARD_X * 2                // 511
  const CARD_RIGHT         = CARD_X + CARD_W                    // 553
  const CARD_PAD           = 12
  const CONTENT_X          = CARD_X + CARD_PAD                  // 54
  const TITLE_UNDERLINE_R  = PAGE_W - MARGIN_X                  // 547
  const WRAP_FULL          = 88
  const WRAP_BODY          = 78

  const pageStreams: string[] = []
  let ops: string[] = []
  let y = CONTENT_TOP
  let pageIndex = 0

  // ── Primitive writers ────────────────────────────────────────────────────
  const setFillColor = (r: number, g: number, b: number) =>
    ops.push(`${r.toFixed(3)} ${g.toFixed(3)} ${b.toFixed(3)} rg`)
  const setStrokeColor = (r: number, g: number, b: number) =>
    ops.push(`${r.toFixed(3)} ${g.toFixed(3)} ${b.toFixed(3)} RG`)
  const resetFill = () => setFillColor(TEXT_DARK.r, TEXT_DARK.g, TEXT_DARK.b)
  const resetStroke = () => setStrokeColor(0, 0, 0)

  const rectFill = (x: number, yB: number, w: number, h: number, r: number, g: number, b: number) => {
    setFillColor(r, g, b)
    ops.push(`${x} ${yB} ${w} ${h} re f`)
    resetFill()
  }
  const rectStroke = (x: number, yB: number, w: number, h: number, r: number, g: number, b: number) => {
    setStrokeColor(r, g, b)
    ops.push(`${x} ${yB} ${w} ${h} re S`)
    resetStroke()
  }
  const line = (x1: number, yy: number, x2: number) => {
    ops.push(`${x1} ${yy} m ${x2} ${yy} l S`)
  }
  const rawText = (
    text: string,
    size: number,
    x: number,
    yy: number,
    font: "F1" | "F2" = "F1"
  ) => ops.push(`BT /${font} ${size} Tf ${x} ${yy} Td (${escapePdfText(text)}) Tj ET`)

  // ── Cursor-based writers ─────────────────────────────────────────────────
  const ensureSpace = (needed: number) => {
    if (y - needed < CONTENT_BOTTOM) beginPage()
  }
  const moveDown = (amt: number) => {
    ensureSpace(amt)
    y -= amt
  }
  const drawText = (
    text: string,
    size = 10,
    x = MARGIN_X,
    font: "F1" | "F2" = "F1",
    lineGap = 6
  ) => {
    ensureSpace(size + lineGap)
    rawText(text, size, x, y, font)
    y -= size + lineGap
  }
  const drawWrapped = (
    text: string,
    size = 10,
    x = MARGIN_X,
    maxChars = WRAP_FULL,
    font: "F1" | "F2" = "F1",
    lineGap = 5
  ) => {
    for (const ln of wrapText(text, maxChars)) drawText(ln, size, x, font, lineGap)
  }

  // ── Page chrome ──────────────────────────────────────────────────────────
  const drawPageHeader = () => {
    rectFill(CARD_X, HEADER_BAR_BOTTOM, CARD_W, HEADER_BAR_H,
      PRODUCT_BLUE.r, PRODUCT_BLUE.g, PRODUCT_BLUE.b)

    const maxH = 38, maxW = 116
    let lH = maxW * (LOGO_HEIGHT / LOGO_WIDTH)
    let lW = maxW
    if (lH > maxH) { lH = maxH; lW = maxH * (LOGO_WIDTH / LOGO_HEIGHT) }
    const lX = CARD_X + 12
    const lY = HEADER_BAR_BOTTOM + (HEADER_BAR_H - lH) / 2
    ops.push(`q ${lW} 0 0 ${lH} ${lX} ${lY} cm /Logo Do Q`)

    setFillColor(1, 1, 1)
    const titleX = lX + lW + 14
    const titleBaseline = HEADER_BAR_BOTTOM + HEADER_BAR_H - 22
    const docNameLabel = clampText(`Document: ${report.document_name || "Unknown Document"}`, 58)
    const versionLabel = clampText(`Version: ${getReportVersionLabel(report)}`, 26)
    rawText("Compliance Report", 16, titleX, titleBaseline, "F2")
    rawText(
      `Report Code: ${report.report_code}`,
      9, titleX, titleBaseline - 15, "F1"
    )
    const gen = `Generated: ${formatReportDate(new Date().toISOString(), false)}`
    // approx char width at 9pt Helvetica → 4.8pt
    const genX = Math.max(titleX + 80, CARD_RIGHT - 12 - gen.length * 4.8)
    rawText(gen, 9, genX, titleBaseline - 15, "F1")
    rawText(docNameLabel, 8.5, titleX, titleBaseline - 27, "F1")
    const versionX = Math.max(titleX + 150, CARD_RIGHT - 12 - versionLabel.length * 4.6)
    rawText(versionLabel, 8.5, versionX, titleBaseline - 27, "F1")
    resetFill()
  }

  const drawPageFooter = () => {
    setStrokeColor(BORDER_SOFT.r, BORDER_SOFT.g, BORDER_SOFT.b)
    line(CARD_X, 44, CARD_RIGHT)
    resetStroke()
    setFillColor(TEXT_MUTED.r, TEXT_MUTED.g, TEXT_MUTED.b)
    rawText(`ComplyCore  -  ${report.report_code}`, 8, CARD_X + 4, 32, "F1")
    const pLabel = `Page ${pageIndex}`
    rawText(pLabel, 8, CARD_RIGHT - 4 - pLabel.length * 4.2, 32, "F1")
    resetFill()
  }

  const beginPage = () => {
    if (ops.length) {
      drawPageFooter()
      pageStreams.push(ops.join("\n"))
    }
    ops = ["0 0 0 rg", "0 0 0 RG", "0.8 w"]
    pageIndex += 1
    drawPageHeader()
    y = CONTENT_TOP
  }

  // ── High-level helpers ───────────────────────────────────────────────────
  const drawSectionTitle = (title: string) => {
    ensureSpace(36)
    moveDown(4)
    setFillColor(PRODUCT_BLUE.r, PRODUCT_BLUE.g, PRODUCT_BLUE.b)
    rawText(title, 13, MARGIN_X, y, "F2")
    y -= 16
    setStrokeColor(0.78, 0.84, 0.97)
    line(MARGIN_X, y + 4, TITLE_UNDERLINE_R)
    resetStroke()
    resetFill()
    y -= 10
  }

  const drawCardBackground = (
    height: number,
    fill: [number, number, number] = [0.98, 0.99, 1.0]
  ) => {
    rectFill(CARD_X, y - height, CARD_W, height, fill[0], fill[1], fill[2])
    rectStroke(CARD_X, y - height, CARD_W, height, BORDER_SOFT.r, BORDER_SOFT.g, BORDER_SOFT.b)
  }

  // Key/value stacked (label on top, value below) used in Identification card.
  const drawKeyValue = (label: string, value: string, wrap = WRAP_BODY) => {
    setFillColor(TEXT_MUTED.r, TEXT_MUTED.g, TEXT_MUTED.b)
    rawText(label.toUpperCase(), 8, CONTENT_X, y, "F2")
    resetFill()
    y -= 12
    for (const ln of wrapText(value || "N/A", wrap)) {
      rawText(ln, 10.5, CONTENT_X, y, "F1")
      y -= 14
    }
    y -= 8
  }
  const measureKeyValue = (value: string, wrap = WRAP_BODY) => {
    const lines = wrapText(value || "N/A", wrap).length || 1
    return 12 + lines * 14 + 8
  }

  // ═══════════════════════════════════════════════════════════════════════
  beginPage()

  // ── Identification ──────────────────────────────────────────────────────
  drawSectionTitle("Identification")
  const idRows: Array<[string, string]> = [
    ["Document / Post Name", report.document_name || "N/A"],
    ["Review Type", report.review_type === "social_post" ? "Social Media" : "Marketing Document"],
    // ["Status", (report.compliance_status || "pending").toUpperCase()],
    [
      "Approval Authority",
      `${report.approval_authority_name || "Unknown"} (${report.approval_role || "Reviewer"})`,
    ],
    ["Approval Timestamp", formatReportDate(report.approval_timestamp) || "Pending"],
  ]
  const idBodyH = idRows.reduce((s, [, v]) => s + measureKeyValue(v), 0)
  const idCardH = idBodyH + CARD_PAD * 2 - 8
  ensureSpace(idCardH + 10)
  drawCardBackground(idCardH, [0.97, 0.98, 1.0])
  moveDown(CARD_PAD + 16)
  idRows.forEach(([k, v]) => drawKeyValue(k, v))
  moveDown(CARD_PAD - 8)

  // ── Findings Summary ────────────────────────────────────────────────────
  drawSectionTitle("Findings Summary")
  const fsH = 62
  ensureSpace(fsH + 10)
  drawCardBackground(fsH, [0.98, 0.99, 1.0])
  moveDown(CARD_PAD + 14)
  setFillColor(TEXT_DARK.r, TEXT_DARK.g, TEXT_DARK.b)
  rawText(`Total Flags: ${report.total_flags || 0}`, 11, CONTENT_X, y, "F2")
  y -= 16
  rawText(
    `High: ${report.high_risk_flags || 0}     Medium: ${report.medium_risk_flags || 0}     Low: ${report.low_risk_flags || 0}`,
    10, CONTENT_X, y, "F1"
  )
  y -= 14
  resetFill()
  moveDown(CARD_PAD + 16)

  // ── AI Findings Overview ────────────────────────────────────────────────
  drawSectionTitle("AI Findings Overview")
  moveDown(2)
  drawText(`Total Findings: ${findings.length}`, 11, CONTENT_X, "F2", 8)
  setFillColor(TEXT_MUTED.r, TEXT_MUTED.g, TEXT_MUTED.b)
  drawText(
    "Each finding is exported on a separate page for clear review.",
    9.5, CONTENT_X, "F1", 8
  )
  resetFill()

  // ── Individual AI Findings (one per page) ───────────────────────────────
  findings.forEach((finding, idx) => {
    beginPage()
    drawSectionTitle(`AI Finding ${idx + 1}`)

    const description = clampText(finding.description   || "", 540)
    const whyRisky    = clampText(finding.why_risky     || "", 540)
    const rationale   = clampText(finding.rationale     || "", 540)
    const suggestion  = clampText(finding.status === "accepted" ? (finding.accepted_suggestion_text || finding.ai_suggestion || "") : (finding.ai_suggestion || ""), 540)

    const subSections: Array<{
      heading: string
      rows: string[]
      fill: [number, number, number]
      stroke: [number, number, number]
    }> = [
      {
        heading: "Claim",
        rows: [
          finding.title || "Untitled finding",
          `Risk: ${String(finding.risk_level || "low").toUpperCase()}     Status: ${String(finding.status || "pending").toUpperCase()}`,
          description || "Not provided",
        ],
        fill:   [0.985, 0.993, 1.0],
        stroke: [0.82,  0.88,  0.96],
      },
      {
        heading: "Why This Is Risky",
        rows:    [whyRisky || "Not provided"],
        fill:    [1.0,  0.97, 0.97],
        stroke:  [0.95, 0.78, 0.78],
      },
      {
        heading: "Rule Rationale",
        rows:    [rationale || "Not provided"],
        fill:    [0.97, 0.985, 1.0],
        stroke:  [0.80, 0.88,  0.96],
      },
      {
        heading: "Suggested Alternative",
        rows:    [suggestion || "Not provided"],
        fill:    [0.96, 1.0,  0.97],
        stroke:  [0.80, 0.92, 0.84],
      },
    ]

    subSections.forEach((sec, sIdx) => {
      const lineCount = sec.rows.reduce(
        (n, r) => n + wrapText(r, WRAP_BODY).length,
        0
      )
      // fixed vertical rhythm inside sub-card:
      //   topPad(12) + heading(14) + body(N*14) + bottomPad(12) = 38 + 14N
      const cardH = 38 + lineCount * 14
      ensureSpace(cardH + 8)

      rectFill(CARD_X, y - cardH, CARD_W, cardH, sec.fill[0], sec.fill[1], sec.fill[2])
      rectStroke(CARD_X, y - cardH, CARD_W, cardH, sec.stroke[0], sec.stroke[1], sec.stroke[2])
      // left accent rail
      rectFill(CARD_X, y - cardH, 4, cardH, sec.stroke[0], sec.stroke[1], sec.stroke[2])

      moveDown(CARD_PAD)
      setFillColor(DEEP_BLUE.r, DEEP_BLUE.g, DEEP_BLUE.b)
      rawText(sec.heading, 11, CONTENT_X, y, "F2")
      resetFill()
      y -= 14
      sec.rows.forEach((row) =>
        drawWrapped(row, 10, CONTENT_X, WRAP_BODY, "F1", 4)
      )
      moveDown(CARD_PAD)
      if (sIdx < subSections.length - 1) moveDown(6)
    })
  })

  // ── Audit Trail ─────────────────────────────────────────────────────────
  const A_ACCENT_W   = 6
  const A_CONTENT_X  = CARD_X + A_ACCENT_W + 6        // 54
  const A_LABEL_W    = 74
  const A_VALUE_X    = A_CONTENT_X + A_LABEL_W         // 128
  const A_VALUE_WRAP = 72
  const A_WRAP       = 84
  const A_RIGHT_EDGE = CARD_RIGHT - 8                  // 545

  const ACCENT_HUMAN = [0.11, 0.45, 0.78] as const    // #1C73C7
  const ACCENT_AI    = [0.80, 0.45, 0.05] as const    // #CC7210
  const ACCENT_WARN  = [0.70, 0.10, 0.10] as const    // red

  const accentColorForEvent = (ev: AuditTrailEvent) => {
    if (ev.is_ai) return ACCENT_AI
    const t = ev.event_type || ""
    if (t.includes("reject") || t.includes("fail")) return ACCENT_WARN
    return ACCENT_HUMAN
  }

  const drawAuditContinuedBanner = () => {
    moveDown(6)
    rectFill(CARD_X, y - 20, CARD_W, 20, 0.11, 0.25, 0.55)
    setFillColor(1, 1, 1)
    rawText("Audit Trail (continued)", 9, A_CONTENT_X, y - 13, "F2")
    resetFill()
    y -= 26
  }

  const drawMetaPair = (labelStr: string, valueStr: string) => {
    const valLines = wrapText(valueStr || "—", A_VALUE_WRAP)
    const rowH = valLines.length * 13
    setFillColor(TEXT_MUTED.r, TEXT_MUTED.g, TEXT_MUTED.b)
    rawText(clampText(labelStr, 14), 8.5, A_CONTENT_X, y, "F2")
    resetFill()
    valLines.forEach((ln, li) =>
      rawText(ln, 9.5, A_VALUE_X, y - li * 13, "F1")
    )
    y -= rowH + 5
  }

  if (auditEvents.length > 0) {
    beginPage()
    drawSectionTitle("Audit Trail")

    // subtitle bar
    rectFill(CARD_X, y - 22, CARD_W, 22, 0.94, 0.96, 0.99)
    rectStroke(CARD_X, y - 22, CARD_W, 22, 0.80, 0.86, 0.94)
    setFillColor(DEEP_BLUE.r, DEEP_BLUE.g, DEEP_BLUE.b)
    rawText(
      `Total events: ${auditEvents.length}    |    Report: ${report.report_code}`,
      10, A_CONTENT_X, y - 14, "F2"
    )
    resetFill()
    y -= 30

    auditEvents.forEach((ev, idx) => {
      let dateStr = "—"
      if (ev.date) {
        const d = new Date(ev.date)
        dateStr = `${d.toLocaleDateString("en-US", { day: "2-digit", month: "short", year: "numeric" })} ${d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}`
      } else if (ev.timestamp) {
        dateStr = formatReportDate(ev.timestamp)
      }
      const userName  = ev.is_ai ? "AI System" : ev.user || "System"
      const userRole  = ev.user_role || ""
      const label     = formatAuditEventLabel(ev.event_type)
      const stageLine = buildAuditStageLineForExport(ev)
      const detailRaw = buildAuditEventDetailForExport(ev)
      // Preserve newlines from formatJsonValueForReadable — do NOT pass through
      // sanitizeAscii here (clampText strips \n); each line is sanitized at render time.
      const detailCapped =
        detailRaw.length <= 8000 ? detailRaw : `${detailRaw.slice(0, 7997)}...`
      const accent    = accentColorForEvent(ev)
      const isAi      = ev.is_ai === true

      const metaRows: Array<[string, string]> = [
        ["Date / Time", dateStr],
        ["Performed by", userRole ? `${userName} (${userRole})` : userName],
        ["Action", label],
      ]
      if (stageLine) metaRows.push(["Stage", stageLine.replace(/^Stage:\s*/i, "")])

      const metaH = metaRows.reduce(
        (acc, [, v]) => acc + wrapText(v || "—", A_VALUE_WRAP).length * 13 + 5,
        0
      )
      const headerH = 20
      // Vertical gap between the header strip and the first meta row
      // (8pt from header bottom to separator + 14pt from separator to first label).
      const HEADER_TO_META_GAP = 8 + 14

      // Split on real newlines so each JSON key ("Finding Code: ...", "Finding Title: ...")
      // renders on its own line. Blank entries become vertical spacers.
      const DETAIL_LINE_H = 13
      const detailLines: string[] = []
      if (detailCapped) {
        const paragraphs = detailCapped.split(/\r?\n/)
        for (const para of paragraphs) {
          const trimmed = para.replace(/\s+$/g, "")
          if (!trimmed.trim()) {
            detailLines.push("")
            continue
          }
          for (const wrapped of wrapText(trimmed, A_WRAP)) {
            detailLines.push(wrapped)
          }
        }
      }
      // height = top gap (2) + header bar (18) + gap below header (8) + lines + bottom pad (6)
      const detailH = detailLines.length
        ? 2 + 18 + 8 + detailLines.length * DETAIL_LINE_H + 6
        : 0
      const innerH =
        CARD_PAD + headerH + HEADER_TO_META_GAP + metaH + (detailH ? 6 + detailH : 0) + CARD_PAD

      const prevY = y
      ensureSpace(innerH + 10)
      if (y > prevY) drawAuditContinuedBanner()
      moveDown(6)

      const top = y
      const bot = top - innerH

      // alternating card tones
      const bg = idx % 2 === 0 ? [0.97, 0.98, 1.0] : [0.99, 0.99, 1.0]
      rectFill(CARD_X, bot, CARD_W, innerH, bg[0], bg[1], bg[2])
      rectStroke(CARD_X, bot, CARD_W, innerH, BORDER_SOFT.r, BORDER_SOFT.g, BORDER_SOFT.b)
      // accent rail
      rectFill(CARD_X, bot, A_ACCENT_W, innerH, accent[0], accent[1], accent[2])

      // header strip
      y = top - CARD_PAD
      const headerTxt = `#${idx + 1}   ${label}${isAi ? "   [AI]" : ""}`
      rectFill(
        A_CONTENT_X - 4,
        y - headerH + 4,
        A_RIGHT_EDGE - A_CONTENT_X + 8,
        headerH,
        accent[0] * 0.1 + 0.9,
        accent[1] * 0.1 + 0.9,
        accent[2] * 0.1 + 0.9
      )
      setFillColor(accent[0], accent[1], accent[2])
      rawText(clampText(headerTxt, 70), 10, A_CONTENT_X, y - 11, "F2")
      resetFill()
      // advance past header strip: strip height + 8pt to the separator line
      y -= headerH + 8

      // separator sits mid-gap between header and first meta row
      setStrokeColor(BORDER_SOFT.r, BORDER_SOFT.g, BORDER_SOFT.b)
      line(A_CONTENT_X, y + 2, A_RIGHT_EDGE)
      resetStroke()
      // breathing room between separator and first meta label
      y -= 14

      metaRows.forEach(([l, v]) => drawMetaPair(l, v))

      if (detailLines.length) {
        y -= 2
        // Header bar: top at y, 18pt tall
        rectFill(A_CONTENT_X - 4, y - 18, A_RIGHT_EDGE - A_CONTENT_X + 8, 18, 0.90, 0.93, 0.98)
        setFillColor(DEEP_BLUE.r, DEEP_BLUE.g, DEEP_BLUE.b)
        rawText("Details", 9, A_CONTENT_X, y - 12, "F2")
        resetFill()
        // Drop below bar (18) + breathing room (8) before first content line
        y -= 18 + 20
        detailLines.forEach((ln) => {
          // empty entries act as vertical spacers between JSON groups (e.g. \n\n)
          if (ln) rawText(ln, 9, A_CONTENT_X + 2, y, "F1")
          y -= DETAIL_LINE_H
        })
        y -= 6
      }

      moveDown(4)
    })
  }

  // ── Finalize last page ──────────────────────────────────────────────────
  if (ops.length) {
    drawPageFooter()
    pageStreams.push(ops.join("\n"))
  }

  const pageCount = pageStreams.length
  const fontRegularObjNum = 3 + pageCount * 2
  const fontBoldObjNum = fontRegularObjNum + 1
  const logoObjNum = fontBoldObjNum + 1
  const objects: string[] = []
  objects.push("1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")

  const kids: string[] = []
  for (let i = 0; i < pageCount; i++) {
    const pageObjNum = 3 + i * 2
    kids.push(`${pageObjNum} 0 R`)
  }
  objects.push(`2 0 obj << /Type /Pages /Kids [${kids.join(" ")}] /Count ${pageCount} >> endobj\n`)

  for (let i = 0; i < pageCount; i++) {
    const pageObjNum = 3 + i * 2
    const contentObjNum = pageObjNum + 1
    const stream = pageStreams[i]
    objects.push(
      `${pageObjNum} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents ${contentObjNum} 0 R /Resources << /Font << /F1 ${fontRegularObjNum} 0 R /F2 ${fontBoldObjNum} 0 R >> /XObject << /Logo ${logoObjNum} 0 R >> >> >> endobj\n`
    )
    objects.push(`${contentObjNum} 0 obj << /Length ${byteLength(stream)} >> stream\n${stream}\nendstream endobj\n`)
  }

  objects.push(`${fontRegularObjNum} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n`)
  objects.push(`${fontBoldObjNum} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> endobj\n`)
  objects.push(
    `${logoObjNum} 0 obj << /Type /XObject /Subtype /Image /Width ${LOGO_WIDTH} /Height ${LOGO_HEIGHT} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter [ /ASCIIHexDecode /DCTDecode ] /Length ${LOGO_HEX.length + 1} >> stream\n${LOGO_HEX}>\nendstream endobj\n`
  )

  let pdf = "%PDF-1.4\n"
  const offsets: number[] = [0]
  for (const obj of objects) {
    offsets.push(byteLength(pdf))
    pdf += obj
  }

  const xrefStart = byteLength(pdf)
  pdf += `xref\n0 ${objects.length + 1}\n`
  pdf += "0000000000 65535 f \n"
  for (let i = 1; i < offsets.length; i++) {
    pdf += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`
  }
  pdf += `trailer << /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`

  return new Blob([pdf], { type: "application/pdf" })
}

export function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.style.display = "none"
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export function downloadReportPdf(
  report: ComplianceReportRow,
  findings: ComplianceFinding[],
  auditEvents: AuditTrailEvent[] = []
) {
  const orgSlug = window.location.pathname.match(/^\/orgs\/([^/]+)/)?.[1]
  if (!orgSlug || !report.id) {
    alert("Cannot download report: missing organization or report ID")
    return
  }
  const url = `${window.location.origin}/api/v1/orgs/${orgSlug}/compliance-reports/${report.id}/pdf?download=true`
  const a = document.createElement("a")
  a.href = url
  a.download = buildReportPdfFileName(report)
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

export function openReportPdfInNewTab(
  report: ComplianceReportRow,
  findings: ComplianceFinding[],
  auditEvents: AuditTrailEvent[] = [],
  existingWindow?: Window | null
): boolean {
  const orgSlug = window.location.pathname.match(/^\/orgs\/([^/]+)/)?.[1]
  if (!orgSlug || !report.id) {
    if (existingWindow) existingWindow.close()
    alert("Cannot view report: missing organization or report ID")
    return false
  }
  const url = `${window.location.origin}/api/v1/orgs/${orgSlug}/compliance-reports/${report.id}/pdf`

  if (existingWindow && !existingWindow.closed) {
    existingWindow.location.href = url
  } else {
    const win = window.open(url, "_blank", "noopener,noreferrer")
    if (!win) return false
  }
  return true
}

export function buildComplianceReportTxt(
  report: ComplianceReportRow,
  findings: ComplianceFinding[],
  auditEvents: AuditTrailEvent[]
): string {
  const findingsSection =
    findings.length === 0
      ? "\nNo compliance flags identified."
      : findings
          .map((f, idx) =>
            `
Claim ${idx + 1}
---------
Title: ${f.title || "Untitled finding"}
Risk: ${(f.risk_level || "low").toUpperCase()}
Status: ${(f.status || "pending").toUpperCase()}
Finding:
${f.description || "Not provided"}

Why This Is Risky:
${f.why_risky || "Not provided"}

Rule Rationale:
${f.rationale || "Not provided"}

Suggested Alternative:
${f.status === "accepted" ? (f.accepted_suggestion_text || f.ai_suggestion || "Not provided") : (f.ai_suggestion || "Not provided")}
--------------------------------------------------`.trim()
          )
          .join("\n\n====================================\n\n")

  const auditSection =
    auditEvents.length > 0
      ? auditEvents
          .map((ev, idx) => {
            const dateStr = ev.date
              ? `${new Date(ev.date).toLocaleDateString("en-US", { day: "2-digit", month: "short", year: "numeric" })} ${new Date(ev.date).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}`
              : ev.timestamp || ""
            const who = ev.is_ai ? "AI System" : ev.user || "System"
            const role = ev.user_role ? ` (${ev.user_role})` : ""
            const label = formatAuditEventLabel(ev.event_type)
            const detail = buildAuditEventDetailForExport(ev)
            const stageLine = buildAuditStageLineForExport(ev)
            const aiTag = ev.is_ai ? " [AI]" : ""
            const n = auditEvents.length
            const lines = [
              "────────────────────────────────────────────────────────",
              ` Event ${idx + 1} of ${n}${aiTag}`,
              "────────────────────────────────────────────────────────",
              `When:     ${dateStr}`,
              `Who:      ${who}${role}`,
              `Action:   ${label}`,
            ]
            if (stageLine) lines.push(stageLine)
            if (detail) {
              lines.push("Details:")
              detail.split("\n").forEach((ln) => lines.push(`   ${ln}`))
            } else {
              lines.push("Details:   (none)")
            }
            return lines.join("\n")
          })
          .join("\n\n")
      : "No audit events recorded."

  return `
Comply Core Compliance Report - ${report.report_code}
------------------------------------------------------
Document: ${report.document_name || "Unknown"}
Version: ${getReportVersionLabel(report)}
Review Type: ${report.review_type === "social_post" ? "Social Media" : "Document"}
Status: ${(report.compliance_status || "pending").toUpperCase()}
Created: ${formatReportDate(report.created_at)}
Approval Authority: ${report.approval_authority_name || "Unknown"} (${report.approval_role || "Reviewer"})
Approval Timestamp: ${formatReportDate(report.approval_timestamp)}

AI Summary
------------
${report.ai_summary || "No automated summary provided."}

Findings Summary
----------------
Total Flags: ${report.total_flags ?? 0}
High Risk: ${report.high_risk_flags ?? 0}
Medium Risk: ${report.medium_risk_flags ?? 0}
Low Risk: ${report.low_risk_flags ?? 0}

Flag Details with Reviewer Decisions
------------------------------------
${findingsSection}

Audit Trail (${auditEvents.length} events)
------------------------------------------
${auditSection}
  `.trim()
}

export function downloadComplianceReportTxt(
  report: ComplianceReportRow,
  findings: ComplianceFinding[],
  auditEvents: AuditTrailEvent[]
) {
  const text = buildComplianceReportTxt(report, findings, auditEvents)
  const blob = new Blob([text], { type: "text/plain" })
  downloadBlob(blob, buildReportTxtFileName(report))
}
