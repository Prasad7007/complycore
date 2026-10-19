"""
ComplyCore – ReportLab PDF generator for compliance reports.

Produces a polished cover page (summary) that matches the reference design:
  • "ComplyCore Compliance Report" title + document name
  • Approved By / Approved On / Report Downloaded metadata row
  • Compliance status badge (APPROVED / REJECTED / PENDING)
  • Flags-by-severity donut chart (High / Medium / Low)
  • Reviewer decisions donut chart (Accepted / Dismissed %)
  • Flags-by-rule horizontal bar chart
  • AI Disclaimer footer
  • Subsequent pages: AI findings detail + Audit Trail table
"""

from __future__ import annotations

import io
import math
import datetime
import os
import re
from typing import Any

# ReportLab imports – hard-fail at import time so the caller gets a clear error
# rather than a cryptic AttributeError later.
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    PageBreak,
    KeepTogether,
    Image,
)
from reportlab.platypus.flowables import Flowable
from reportlab.graphics.shapes import (
    Drawing,
    Wedge,
    String,
    Line,
    Rect,
    Circle,
    Group,
)
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics import renderPDF

# ── Palette ───────────────────────────────────────────────────────────────────
BRAND_BLUE   = colors.HexColor("#1F4ED8")
BRAND_DARK   = colors.HexColor("#0F2057")
TEXT_DARK    = colors.HexColor("#1a1a2e")
TEXT_MUTED   = colors.HexColor("#6B7280")
BORDER_GRAY  = colors.HexColor("#E5E7EB")
BG_LIGHT     = colors.HexColor("#F9FAFB")

HIGH_COLOR   = colors.HexColor("#DC2626")   # red-600
MED_COLOR    = colors.HexColor("#D97706")   # amber-600
LOW_COLOR    = colors.HexColor("#2563EB")   # blue-600

ACCEPT_COLOR = colors.HexColor("#16A34A")   # green-600
DISMISS_COLOR= colors.HexColor("#9CA3AF")   # gray-400

GREEN_BG     = colors.HexColor("#F0FDF4")
GREEN_BORDER = colors.HexColor("#16A34A")
RED_BG       = colors.HexColor("#FEF2F2")
RED_BORDER   = colors.HexColor("#DC2626")
AMBER_BG     = colors.HexColor("#FFFBEB")
AMBER_BORDER = colors.HexColor("#D97706")

PAGE_W, PAGE_H = A4   # 595.28 x 841.89 pt
MARGIN = 28 * mm


# ─────────────────────────────────────────────────────────────────────────────
# Helper: human-readable date
# ─────────────────────────────────────────────────────────────────────────────
def _fmt_date(iso, include_time: bool = True, timezone_str: str = "America/New_York") -> str:
    if not iso:
        return "—"
    try:
        import zoneinfo
        # Handle native datetime objects (from DB) directly
        if isinstance(iso, datetime.datetime):
            dt = iso
        else:
            iso = str(iso)
            if iso.endswith("Z"):
                iso = iso[:-1] + "+00:00"
            dt = datetime.datetime.fromisoformat(iso)
            
        # Ensure dt is timezone-aware (assume UTC if naive)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            
        # Convert to requested Timezone for the report
        dt = dt.astimezone(zoneinfo.ZoneInfo(timezone_str))

        months = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]
        m = months[dt.month - 1]
        date_str = f"{m} {dt.day:02d}, {dt.year}"
        if include_time:
            return f"{date_str} · {dt.hour:02d}:{dt.minute:02d}"
        return date_str
    except Exception:
        return str(iso)[:20]


def _fmt_downloaded_date(timezone_str: str = "America/New_York") -> str:
    import zoneinfo
    now = datetime.datetime.now(datetime.timezone.utc).astimezone(zoneinfo.ZoneInfo(timezone_str))
    months = ["Jan","Feb","Mar","Apr","May","Jun",
              "Jul","Aug","Sep","Oct","Nov","Dec"]
    return f"{months[now.month-1]} {now.day:02d}, {now.year}"


def _safe(text: str | None, max_len: int = 200) -> str:
    s = str(text or "").strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Donut chart flowable
# ─────────────────────────────────────────────────────────────────────────────
class DonutChart(Flowable):
    """Simple donut chart rendered as a ReportLab Drawing."""

    def __init__(
        self,
        slices: list[tuple[float, colors.Color]],
        center_label: str,
        center_sub: str,
        width: float = 100,
        height: float = 100,
        hole_radius: float = 28,
    ):
        super().__init__()
        self.slices = slices          # list of (value, color)
        self.center_label = center_label
        self.center_sub = center_sub
        self.width = width
        self.height = height
        self.hole_radius = hole_radius

    def wrap(self, *args):
        return self.width, self.height

    def draw(self):
        cx = self.width / 2
        cy = self.height / 2
        r = min(cx, cy) - 4
        total = sum(v for v, _ in self.slices) or 1
        canvas = self.canv

        start = 90
        for value, col in self.slices:
            angle = 360 * value / total
            canvas.setFillColor(col)
            canvas.setStrokeColor(colors.white)
            canvas.setLineWidth(1.5)
            canvas.wedge(
                cx - r, cy - r, cx + r, cy + r,
                start, -angle,
                stroke=1, fill=1,
            )
            start -= angle

        # white hole
        canvas.setFillColor(colors.white)
        canvas.setStrokeColor(colors.white)
        canvas.circle(cx, cy, self.hole_radius, stroke=0, fill=1)

        # center text
        canvas.setFont("Helvetica-Bold", 14)
        canvas.setFillColor(TEXT_DARK)
        lw = canvas.stringWidth(self.center_label, "Helvetica-Bold", 14)
        canvas.drawString(cx - lw / 2, cy + 4, self.center_label)

        canvas.setFont("Helvetica", 6)
        canvas.setFillColor(TEXT_MUTED)
        y_sub = cy - 6
        for line in self.center_sub.split('\n'):
            sw = canvas.stringWidth(line, "Helvetica", 6)
            canvas.drawString(cx - sw / 2, y_sub, line)
            y_sub -= 7


# ─────────────────────────────────────────────────────────────────────────────
# Horizontal bar chart flowable
# ─────────────────────────────────────────────────────────────────────────────
class HBarChart(Flowable):
    """Horizontal bar chart for rules breakdown."""

    def __init__(
        self,
        items: list[tuple[str, int]],   # (label, count)
        max_val: int,
        width: float,
        bar_h: float = 8,
        row_gap: float = 14,
    ):
        super().__init__()
        self.items = items
        self.max_val = max_val or 1
        self.width = width
        self.bar_h = bar_h
        self.row_gap = row_gap
        self.height = len(items) * row_gap + 4

    def wrap(self, *args):
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        label_w = 240
        count_w = 24
        bar_area = self.width - label_w - count_w - 8
        y = self.height - self.row_gap

        for label, count in self.items:
            # label
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(TEXT_DARK)
            canvas.drawString(0, y + 1, _safe(label, 50))

            # bar bg
            bx = label_w
            bar_filled = bar_area * (count / self.max_val)
            canvas.setFillColor(BORDER_GRAY)
            canvas.rect(bx, y, bar_area, self.bar_h, stroke=0, fill=1)

            # bar fill
            canvas.setFillColor(BRAND_BLUE)
            if bar_filled > 0:
                canvas.rect(bx, y, bar_filled, self.bar_h, stroke=0, fill=1)

            # count
            canvas.setFont("Helvetica-Bold", 8)
            canvas.setFillColor(TEXT_DARK)
            canvas.drawRightString(self.width, y + 1, str(count))

            y -= self.row_gap


# ─────────────────────────────────────────────────────────────────────────────
# Status badge flowable
# ─────────────────────────────────────────────────────────────────────────────
class StatusBadge(Flowable):
    def __init__(self, status: str):
        super().__init__()
        s = (status or "").lower()
        if s in ("compliant", "pass", "approved"):
            self.label = "APPROVED"
            self.bg = GREEN_BG
            self.border = GREEN_BORDER
            self.text_color = GREEN_BORDER
            self.icon = "✓"
        elif s in ("non_compliant", "fail", "rejected"):
            self.label = "REJECTED"
            self.bg = RED_BG
            self.border = RED_BORDER
            self.text_color = RED_BORDER
            self.icon = "✗"
        else:
            self.label = "PENDING REVIEW"
            self.bg = AMBER_BG
            self.border = AMBER_BORDER
            self.text_color = AMBER_BORDER
            self.icon = "○"
        self.width = 140
        self.height = 48

    def wrap(self, *args):
        return self.width, self.height

    def draw(self):
        c = self.canv
        r = 6
        w, h = self.width, self.height
        # rounded rect
        c.setFillColor(self.bg)
        c.setStrokeColor(self.border)
        c.setLineWidth(1)
        c.roundRect(0, 0, w, h, r, stroke=1, fill=1)
        # icon
        c.setFillColor(self.border)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(10, h - 20, self.icon)
        # label
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(24, h - 19, self.label)
        # sub text
        c.setFont("Helvetica", 7)
        c.setFillColor(self.text_color)
        sub = "Reviewed and approved in accordance" if self.label == "APPROVED" else "Review decision recorded"
        c.drawString(10, 14, sub)
        if self.label == "APPROVED":
            c.drawString(10, 5, "with company compliance requirements.")


# ─────────────────────────────────────────────────────────────────────────────
# Page header/footer callbacks
# ─────────────────────────────────────────────────────────────────────────────
def _make_page_header_footer(report_doc_name: str, report_code: str):
    def on_page(canvas, doc):
        canvas.saveState()
        # top rule
        canvas.setStrokeColor(BORDER_GRAY)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - 18 * mm, PAGE_W - MARGIN, PAGE_H - 18 * mm)
        # header left: product name
        import os
        logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "report-logo.png"))
        if os.path.exists(logo_path):
            canvas.drawImage(logo_path, MARGIN, PAGE_H - 15 * mm, width=12, height=12, preserveAspectRatio=True, mask='auto')
            text_x = MARGIN + 16
        else:
            text_x = MARGIN

        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(BRAND_BLUE)
        canvas.drawString(text_x, PAGE_H - 14 * mm, "ComplyCore")

        # footer rule
        canvas.setStrokeColor(BORDER_GRAY)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        # footer left
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawString(MARGIN, 9 * mm, f"ComplyCore · {_safe(report_doc_name, 80)}")
        # footer right: page number
        canvas.drawRightString(PAGE_W - MARGIN, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return on_page


# ─────────────────────────────────────────────────────────────────────────────
# Styles
# ─────────────────────────────────────────────────────────────────────────────
def _build_styles():
    base = getSampleStyleSheet()
    normal = base["Normal"]

    def S(name, **kw) -> ParagraphStyle:
        parent = kw.pop("parent", normal)
        return ParagraphStyle(name, parent=parent, **kw)

    return {
        "doc_type":    S("doc_type",  fontSize=8.5, textColor=BRAND_BLUE, fontName="Helvetica-Bold",
                          spaceBefore=0, spaceAfter=2, tracking=1),
        "report_title":S("rpt_title", fontSize=22, textColor=TEXT_DARK, fontName="Times-Bold",
                          spaceBefore=0, spaceAfter=2, leading=26),
        "doc_name":    S("doc_name",  fontSize=15, textColor=TEXT_DARK, fontName="Times-Bold",
                          spaceBefore=0, spaceAfter=0),
        "meta_label":  S("meta_lbl",  fontSize=7,  textColor=TEXT_MUTED, fontName="Helvetica-Bold",
                          spaceBefore=0, spaceAfter=1, tracking=0.5),
        "meta_value":  S("meta_val",  fontSize=9,  textColor=TEXT_DARK,  fontName="Helvetica",
                          spaceBefore=0, spaceAfter=0),
        "section_hd":  S("sec_hd",    fontSize=7.5,textColor=BRAND_BLUE, fontName="Helvetica-Bold",
                          spaceBefore=0, spaceAfter=4, tracking=0.8),
        "exec_summary":S("exec_sum",  fontSize=8.5,textColor=TEXT_DARK,  fontName="Helvetica",
                          spaceBefore=0, spaceAfter=0, leading=13),
        "legend_label":S("legend",    fontSize=8,  textColor=TEXT_DARK,  fontName="Helvetica",
                          spaceBefore=0, spaceAfter=2),
        "finding_title":S("find_t",   fontSize=10, textColor=TEXT_DARK, fontName="Helvetica-Bold",
                          spaceBefore=4, spaceAfter=2, leading=13),
        "finding_body": S("find_b",   fontSize=8.5,textColor=TEXT_DARK, fontName="Helvetica",
                          spaceBefore=0, spaceAfter=2, leading=12),
        "tag_pill":    S("tag",       fontSize=8,  textColor=BRAND_BLUE, fontName="Helvetica-Bold",
                          spaceBefore=0, spaceAfter=0),
        "audit_label": S("audit_lbl", fontSize=7.5,textColor=TEXT_MUTED, fontName="Helvetica-Bold",
                          spaceBefore=0, spaceAfter=0),
        "audit_value": S("audit_val", fontSize=8.5,textColor=TEXT_DARK,  fontName="Helvetica",
                          spaceBefore=0, spaceAfter=0, leading=11),
        "disclaimer":  S("disc",      fontSize=7.5,textColor=TEXT_DARK,  fontName="Helvetica",
                          spaceBefore=0, spaceAfter=0, leading=11),
        "page_title":  S("pg_title",  fontSize=14, textColor=TEXT_DARK,  fontName="Helvetica-Bold",
                          spaceBefore=6, spaceAfter=4),
        "normal":      normal,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Cover-page summary elements
# ─────────────────────────────────────────────────────────────────────────────
def _cover_meta_table(approved_by: str, approved_on: str, downloaded: str, styles, content_w: float) -> Table:
    """Three-column meta row: Approved By | Approved On | Report Downloaded."""

    def col(label: str, value: str):
        return [
            Paragraph(label, styles["meta_label"]),
            Paragraph(value, styles["meta_value"]),
        ]

    data = [[col(c[0], c[1]) for c in [
        ("APPROVED BY",       approved_by),
        ("APPROVED ON",       approved_on),
        ("REPORT DOWNLOADED", downloaded),
    ]]]
    t = Table(data, colWidths=[content_w / 3.0, content_w / 3.0, content_w / 3.0])
    t.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("BOX",         (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("BACKGROUND",  (0, 0), (-1, -1), BG_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",(0, 0), (-1, -1), 12),
        ("TOPPADDING",  (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0,0), (-1, -1), 10),
        ("LINEBEFORE",  (1, 0), (2, 0), 0.5, BORDER_GRAY),
    ]))
    return t


def _severity_legend(high: int, med: int, low: int, styles) -> Table:
    rows = [
        (HIGH_COLOR, str(high),  "High"),
        (MED_COLOR,  str(med),   "Medium"),
        (LOW_COLOR,  str(low),   "Low"),
    ]
    data = []
    for col, count, label in rows:
        swatch = Table([[""]], colWidths=[8], rowHeights=[8])
        swatch.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(0,0), col),
            ("TOPPADDING",(0,0),(0,0),0),("BOTTOMPADDING",(0,0),(0,0),0),
            ("LEFTPADDING",(0,0),(0,0),0),("RIGHTPADDING",(0,0),(0,0),0),
        ]))
        data.append([swatch,
                     Paragraph(f"<b>{count}</b>", styles["legend_label"]),
                     Paragraph(label, styles["legend_label"])])

    t = Table(data, colWidths=[12, 22, 50])
    t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))
    return t


def _reviewer_legend(accepted: int, dismissed: int, rejected: int, styles) -> Table:
    rows = [
        (ACCEPT_COLOR,  str(accepted),  "Accepted"),
        (DISMISS_COLOR, str(dismissed), "Dismissed"),
    ]
    rows.append((colors.HexColor("#EF4444"), str(rejected), "Rejected"))
    data = []
    for col, count, label in rows:
        swatch = Table([[""]], colWidths=[8], rowHeights=[8])
        swatch.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(0,0), col),
            ("TOPPADDING",(0,0),(0,0),0),("BOTTOMPADDING",(0,0),(0,0),0),
            ("LEFTPADDING",(0,0),(0,0),0),("RIGHTPADDING",(0,0),(0,0),0),
        ]))
        data.append([swatch,
                     Paragraph(f"<b>{count}</b>", styles["legend_label"]),
                     Paragraph(label, styles["legend_label"])])

    t = Table(data, colWidths=[12, 22, 56])
    t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Audit trail table
# ─────────────────────────────────────────────────────────────────────────────
_AUDIT_EVENT_LABELS: dict[str, str] = {
    "uploaded":                  "Document uploaded",
    "document_upload":           "Document uploaded",
    "reuploaded":                "Document re-uploaded",
    "ai_classification_completed": "AI classification completed",
    "ai_analysis_started":       "AI analysis started",
    "ai_analysis_completed":     "AI analysis completed",
    "ai_analysis_failed":        "AI analysis failed",
    "ai_analysis_skipped":       "AI analysis skipped",
    "submit_to_compliance":      "Sent to compliance",
    "submit_to_marketing":       "Sent to marketing",
    "claim":                     "Claimed for review",
    "claimed":                   "Claimed for review",
    "review_claimed":            "Claimed for review",
    "approve":                   "Approved",
    "approve_and_lock":          "Approved & Locked",
    "sme_approve":               "SME approved",
    "reject":                    "Rejected",
    "request_changes":           "Changes requested",
    "changes_requested":         "Changes requested",
    "finding_accepted":          "Finding accepted",
    "finding_accepted_global":   "Findings accepted (global)",
    "finding_accepted_local":    "Finding accepted (suggestion)",
    "finding_rejected":          "Finding rejected",
    "finding_rejected_global":   "Findings rejected (global)",
    "finding_dismissed":         "Finding dismissed",
    "finding_comment_added":     "Feedback on finding",
    "comment_added":             "Comment added",
    "assigned":                  "Reviewer assigned",
    "publish":                   "Published",
    "document_published":        "Published",
    "document_locked":           "Document locked",
    "workflow_stage_changed":    "Stage changed",
    "review_completed":          "Review completed",
}


def _group_audit_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # High-level allowed events (filter out comments, assignments, etc.)
    allowed_types = {
        "uploaded", "document_upload", "reuploaded",
        "ai_classification_completed",
        "ai_analysis_started",
        "ai_analysis_completed",
        "submit_to_compliance",
        "submit_to_marketing",
        "claim", "claimed", "review_claimed",
        "approve", "approve_and_lock", "document_locked", "publish", "document_published",
        "workflow_stage_changed", "review_completed",
        "request_changes", "changes_requested", "reject"
    }
    
    finding_types = {
        "finding_accepted_global", "finding_accepted_local", "finding_accepted",
        "finding_rejected_global", "finding_rejected",
        "finding_dismissed"
    }
    
    final_events = []
    finding_groups = {}
    
    def flush_findings():
        normalized = {}
        meta = {}
        for ft, fevs in finding_groups.items():
            if "accepted" in ft:
                k = "finding_accepted_global"
            elif "rejected" in ft:
                k = "finding_rejected_global"
            elif "dismissed" in ft:
                k = "finding_dismissed"
            else:
                k = ft
                
            if k not in normalized:
                normalized[k] = []
                meta[k] = None
                
            for e in fevs:
                if not meta[k] or str(e.get("timestamp") or "") >= str(meta[k].get("timestamp") or ""):
                    meta[k] = e
                    
                if "grouped_events" in e:
                    normalized[k].extend(e["grouped_events"])
                else:
                    normalized[k].append(e)
            
        # Add to final events in a consistent order
        for k in ["finding_accepted_global", "finding_rejected_global", "finding_dismissed"]:
            fevs = normalized.get(k)
            if fevs:
                group_ev = dict(meta[k])
                group_ev["event_type"] = k
                group_ev["grouped_events"] = fevs
                final_events.append(group_ev)
                
        finding_groups.clear()
    
    for ev in events:
        t = (ev.get("event_type") or "").lower()
        if t in finding_types:
            if t not in finding_groups:
                finding_groups[t] = []
            finding_groups[t].append(ev)
        elif t in allowed_types:
            # Flush accumulated findings right before approval or stage transitions
            if t in ("approve", "approve_and_lock", "document_locked", "publish", "document_published", "submit_to_compliance", "submit_to_marketing", "workflow_stage_changed", "review_completed"):
                flush_findings()
            final_events.append(ev)
            
    flush_findings()
    return final_events


def _audit_label(ev: dict) -> str:
    t = (ev.get("event_type") or "").lower()
    prev = (ev.get("previous_stage") or "").lower()
    new_stage = (ev.get("workflow_stage") or "").lower()

    if "grouped_events" in ev:
        # De-duplicate by claim so the count matches the UI finding cards,
        # not the number of individual rule-level findings inside those cards.
        unique_claims: set[str] = set()
        for gev in ev["grouped_events"]:
            f = gev.get("finding") or {}
            chash = str(f.get("canonical_claim_hash") or "").strip()
            cid   = str(f.get("claim_id") or "").strip()
            ctxt  = str(f.get("claim_text") or f.get("finding_title") or f.get("finding_id") or "").strip()[:200]
            if chash:
                unique_claims.add(f"h:{chash}")
            elif cid:
                unique_claims.add(f"cid:{cid}")
            elif ctxt:
                unique_claims.add(f"txt:{ctxt}")

        # Fall back to raw event count only when no claim fields are present at all
        count = len(unique_claims) if unique_claims else len(ev["grouped_events"])

        if count > 1:
            if t in ("finding_accepted_global", "finding_accepted", "finding_accepted_local"):
                return f"{count} findings accepted"
            if t in ("finding_rejected_global", "finding_rejected"):
                return f"{count} findings rejected"
            if t == "finding_dismissed":
                return f"{count} findings dismissed"
        elif count == 1:
            if t in ("finding_accepted_global", "finding_accepted", "finding_accepted_local"):
                return "1 finding accepted"
            if t in ("finding_rejected_global", "finding_rejected"):
                return "1 finding rejected"
            if t == "finding_dismissed":
                return "1 finding dismissed"


    if t == "approve":
        if prev == "sme_review":   return "Sent to marketing review"
        if prev == "marketing_review": return "Sent to compliance"
    if t == "workflow_stage_changed":
        if new_stage == "sme_review": return "Sent to SME"
        if new_stage == "compliance_review": return "Marketing sent to compliance"
        if new_stage == "marketing_review": return "Sent to marketing"
    if t == "review_completed":
        if new_stage == "sme_review": return "Sent to SME"
        if new_stage == "compliance_review": return "Marketing sent to compliance"
        if new_stage == "marketing_review": return "Sent to marketing"
    if t in ("document_locked", "approve_and_lock", "lock"):
        return "Approved & Locked"
    if t in ("document_published", "publish"):
        return "Published"
        
    stg = prev or new_stage
    is_compliance = "compliance" in stg
    is_sme = "sme" in stg
    suffix = ""
    if is_compliance: suffix = " (compliance)"
    elif is_sme: suffix = " (sme)"

    if t in ("reject",):
        return f"Rejected{suffix}"
    if t in ("request_changes", "changes_requested"):
        return f"Changes requested{suffix}"
    if t in ("claim", "claimed", "review_claimed"):
        return f"Claimed for review{suffix}"
        
    label = _AUDIT_EVENT_LABELS.get(t)
    if label:
        return label
    return t.replace("_", " ").title()


def _audit_desc(ev: dict) -> str:
    t = (ev.get("event_type") or "").lower()

    if "grouped_events" in ev:
        count = len(ev["grouped_events"])
        if count > 1:
            if t in ("finding_accepted_global", "finding_accepted", "finding_accepted_local"):
                return "All AI findings reviewed and accepted across the document."
            if t in ("finding_rejected_global", "finding_rejected"):
                return "Findings reviewed and rejected."
            if t == "finding_dismissed":
                return "Findings reviewed and dismissed."
        elif count == 1:
            if t in ("finding_accepted_global", "finding_accepted", "finding_accepted_local"):
                return "AI finding reviewed and accepted."
            if t in ("finding_rejected_global", "finding_rejected"):
                return "Finding reviewed and rejected."
            if t == "finding_dismissed":
                return "Finding reviewed and dismissed."

    desc = (ev.get("description") or "").strip()
    if desc and not desc.lower().startswith("workflow action:"):
        return desc
    if t in ("uploaded", "document_upload"):
        return "Source document submitted for review."
    if t == "ai_classification_completed":
        return "Document type detected and classified."
    if t == "ai_analysis_started":
        return "Automated review against the active rule set initiated."
    if t == "ai_analysis_completed":
        try:
            import json
            d = json.loads(ev.get("details") or "{}")
            n = d.get("findings_count")
            if n is not None:
                return f"{n} finding{'s' if n!=1 else ''} identified and saved."
        except Exception:
            pass
        return "AI compliance review completed."
    if t == "submit_to_compliance":
        return "Routed from marketing review to compliance review."
    if t == "submit_to_marketing":
        return "Routed back to marketing review."
    if t in ("claim", "claimed", "review_claimed"):
        return "Reviewer took ownership of the queue item."
    if t == "approve_and_lock":
        return "Document approved and locked. Workflow complete."
    if ev.get("comment"):
        return str(ev["comment"])
    return ""


def _fmt_audit_ts(ev: dict, timezone_str: str = "America/New_York") -> str:
    if "grouped_events" in ev and len(ev["grouped_events"]) > 1:
        first_ev = ev["grouped_events"][0]
        last_ev = ev["grouped_events"][-1]
        t1 = first_ev.get("time")
        t2 = last_ev.get("time")
        if t1 and t2 and t1 != t2:
            return f"{t1} - {t2}"
        if t1:
            return t1

    ts = ev.get("timestamp") or ""
    if not ts:
        date_p = ev.get("date", "")
        time_p = ev.get("time", "")
        if date_p:
            return f"{date_p} {time_p}".strip()
        return "—"
    return _fmt_date(ts, include_time=True, timezone_str=timezone_str)


def _audit_performer(ev: dict) -> str:
    if ev.get("is_ai"):
        return "Complycore"
    name = ev.get("grouping_user_name") or ev.get("user") or "System"
    role = ev.get("user_role") or ""
    if role:
        parts = []
        for r in role.split(","):
            r = r.strip().lower()
            if r == "super_admin": parts.append("Super Admin")
            elif r == "sme":       parts.append("SME")
            else:                  parts.append(r.capitalize())
        role_str = ", ".join(p for p in parts if p)
        return f"{name}\n{role_str}"
    return name


# ─────────────────────────────────────────────────────────────────────────────
# Main generator
# ─────────────────────────────────────────────────────────────────────────────
def generate_report_pdf(
    report: dict[str, Any],
    findings: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
    user_timezone: str = "America/New_York",
) -> bytes:
    """
    Build a full compliance report PDF using ReportLab and return bytes.

    Parameters
    ----------
    report       : flat dict of ComplianceReport fields
    findings     : list of finding dicts
    audit_events : list of audit event dicts (chronological)
    """
    buf = io.BytesIO()
    styles = _build_styles()

    # ── Document setup ────────────────────────────────────────────────────
    doc_name    = _safe(report.get("document_name") or "Unknown Document", 80)
    report_code = _safe(report.get("report_code") or "REPORT", 30)
    auth_name   = _safe(report.get("approval_authority_name") or "—")
    auth_role   = _safe(report.get("approval_role") or "")
    approved_by = f"{auth_name} · {auth_role}" if auth_role else auth_name
    approved_on = _fmt_date(report.get("approval_timestamp"), include_time=True, timezone_str=user_timezone)
    comp_status = _safe(report.get("compliance_status") or "pending")
    review_type = report.get("review_type") or "marketing"
    review_label = "SOCIAL MEDIA POST REVIEW" if "social" in review_type.lower() else "MARKETING DOCUMENT REVIEW"

    # Calculate reviewer decisions and severity by grouped findings (cards)
    findings_by_claim_for_counts = {}
    for f in findings:
        canonical_hash = str(f.get("canonical_claim_hash") or "").strip()
        claim_id = str(f.get("claim_id") or "").strip()
        claim_text = str(f.get("claim_text") or f.get("title") or f.get("id") or "").strip()[:200]
        
        if canonical_hash:
            fallback_key = f"h:{canonical_hash}"
        elif claim_id:
            fallback_key = f"cid:{claim_id}"
        else:
            fallback_key = f"txt:{claim_text}"
            
        if fallback_key not in findings_by_claim_for_counts:
            findings_by_claim_for_counts[fallback_key] = []
        findings_by_claim_for_counts[fallback_key].append(f)

    accepted = 0
    dismissed = 0
    rejected_f = 0
    
    total_flags = 0
    high_flags = 0
    med_flags = 0
    low_flags = 0
    severity_order = {"high": 3, "critical": 3, "medium": 2, "low": 1}

    for claim_key, claim_findings in findings_by_claim_for_counts.items():
        total_flags += 1
        
        # Severity calculation for the claim
        highest_val = 0
        for f in claim_findings:
            r = (f.get("risk_level") or "low").lower()
            val = severity_order.get(r, 1)
            if val > highest_val:
                highest_val = val
                
        if highest_val == 3:
            high_flags += 1
        elif highest_val == 2:
            med_flags += 1
        else:
            low_flags += 1

        statuses = [str(f.get("status") or "pending").lower() for f in claim_findings]
        if "accepted" in statuses:
            accepted += 1
        elif "rejected" in statuses:
            rejected_f += 1
        elif "dismissed" in statuses:
            dismissed += 1

    # Rules breakdown
    rule_counts: dict[str, int] = {}
    for f in findings:
        rule_code = _safe(f.get("rule_code") or "")
        title = _safe(f.get("title") or "")
        
        rule_label = None
        
        # Extract from title (e.g. "Violation of Rule 2: ...")
        if "Rule " in title:
            try:
                after_rule = title.split("Rule ", 1)[1]
                if ":" in after_rule:
                    num = after_rule.split(":", 1)[0].strip()
                    desc = after_rule.split(":", 1)[1].strip()
                    if desc:
                        rule_label = f"Rule {num}: {desc}"
                    else:
                        rule_label = f"Rule {num}"
                else:
                    num = after_rule.split()[0].strip()
                    rule_label = f"Rule {num}"
            except Exception:
                pass
                
        # Fallback to rule_code
        if not rule_label and rule_code:
            key = rule_code.replace("RULE-", "").strip()
            if key.isdigit():
                rule_label = f"Rule {key}"
                
        # Final fallback
        if not rule_label:
            rule_label = "Unclassified"
            
        rule_counts[rule_label] = rule_counts.get(rule_label, 0) + 1
        
    rule_items = sorted(rule_counts.items(), key=lambda x: -x[1])[:8]
    max_rule_count = max((c for _, c in rule_items), default=1)

    # Executive summary
    exec_parts = []
    if total_flags:
        exec_parts.append(f"{total_flags} flag{'s' if total_flags!=1 else ''} were raised"
                          + (f" across {len(rule_counts)} compliance rule{'s' if len(rule_counts)!=1 else ''}" if rule_counts else "") + ".")
    if accepted and not dismissed:
        exec_parts.append("All were reviewed and accepted by compliance — none dismissed.")
    elif accepted or dismissed:
        exec_parts.append(f"{accepted} accepted, {dismissed} dismissed by compliance.")
    if not exec_parts:
        exec_parts.append("No compliance flags were identified during the review.")
    exec_summary = " ".join(exec_parts)

    # ── Doc template ─────────────────────────────────────────────────────
    on_page = _make_page_header_footer(doc_name, report_code)

    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        PAGE_W - doc.leftMargin - doc.rightMargin,
        PAGE_H - doc.topMargin - doc.bottomMargin,
        id="main",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])

    content_w = PAGE_W - 2 * MARGIN

    story: list = []

    # ════════════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ════════════════════════════════════════════════════════════════════════

    # ── Title block ───────────────────────────────────────────────────────
    import os
    logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "report-logo.png"))
    logo_img = Image(logo_path, width=45, height=22, kind='proportional') if os.path.exists(logo_path) else ""
    
    brand_text = [
        Paragraph("ComplyCore", ParagraphStyle("BrandName", fontSize=15, textColor=TEXT_DARK, fontName="Times-Bold", leading=16)),
        Spacer(1, 2),
        Paragraph("COMPLIANCE<br/>INTELLIGENCE", ParagraphStyle("BrandSub", fontSize=6.5, textColor=TEXT_MUTED, fontName="Helvetica-Bold", leading=7.5, tracking=1.5))
    ]
    brand_table = Table([[logo_img, brand_text]], colWidths=[48, 250])
    brand_table.setStyle(TableStyle([
        ("VALIGN", (0,0),(-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0),(-1,-1), 0),
        ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING", (0,0),(-1,-1), 0),
    ]))

    top_row_table = Table(
        [[brand_table, StatusBadge(comp_status)]],
        colWidths=[content_w - 140, 140],
    )
    top_row_table.setStyle(TableStyle([
        ("VALIGN",  (0,0),(-1,-1), "TOP"),
        ("LEFTPADDING", (0,0),(-1,-1), 0),
        ("RIGHTPADDING",(0,0),(-1,-1), 0),
        ("TOPPADDING",  (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1), 0),
    ]))
    
    story.append(top_row_table)
    story.append(Spacer(1, 24))
    story.append(Paragraph(review_label, styles["doc_type"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("ComplyCore Compliance Report", styles["report_title"]))
    story.append(Paragraph(doc_name, ParagraphStyle("doc_name_grey", parent=styles["report_title"], textColor=TEXT_MUTED)))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY))
    story.append(Spacer(1, 8))

    # ── Meta row ─────────────────────────────────────────────────────────
    story.append(_cover_meta_table(approved_by, approved_on, _fmt_downloaded_date(timezone_str=user_timezone), styles, content_w))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY))
    story.append(Spacer(1, 8))

    # ── Executive summary ─────────────────────────────────────────────────
    story.append(Paragraph("EXECUTIVE SUMMARY", styles["section_hd"]))
    story.append(Paragraph(exec_summary, styles["exec_summary"]))
    story.append(Spacer(1, 12))

    # ── Charts row: Flags by severity | Reviewer decisions ───────────────
    chart_w = (content_w - 16) / 2

    # Severity donut
    sev_slices = []
    if high_flags: sev_slices.append((high_flags, HIGH_COLOR))
    if med_flags:  sev_slices.append((med_flags,  MED_COLOR))
    if low_flags:  sev_slices.append((low_flags,  LOW_COLOR))
    if not sev_slices: sev_slices = [(1, BORDER_GRAY)]

    sev_donut = DonutChart(
        slices=sev_slices,
        center_label=str(total_flags),
        center_sub="TOTAL\nFLAGS",
        width=90, height=90,
        hole_radius=28,
    )
    sev_legend = _severity_legend(high_flags, med_flags, low_flags, styles)

    # Reviewer decisions donut
    rev_total = accepted + dismissed + rejected_f or 1
    rev_pct = round(100 * accepted / rev_total)
    rev_slices = []
    if accepted:  rev_slices.append((accepted,  ACCEPT_COLOR))
    if dismissed: rev_slices.append((dismissed, DISMISS_COLOR))
    if rejected_f:rev_slices.append((rejected_f, colors.HexColor("#EF4444")))
    if not rev_slices: rev_slices = [(1, BORDER_GRAY)]

    rev_donut = DonutChart(
        slices=rev_slices,
        center_label=f"{rev_pct}%",
        center_sub="ACCEPTED",
        width=90, height=90,
        hole_radius=28,
    )
    rev_legend = _reviewer_legend(accepted, dismissed, rejected_f, styles)

    # Severity box
    sev_inner = Table(
        [[sev_donut, sev_legend]],
        colWidths=[96, chart_w - 96 - 16],
    )
    sev_inner.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))

    # Reviewer box
    rev_inner = Table(
        [[rev_donut, rev_legend]],
        colWidths=[96, chart_w - 96 - 16],
    )
    rev_inner.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))

    def _box(inner_content, label: str):
        return [
            Paragraph(label, styles["section_hd"]),
            Spacer(1, 4),
            inner_content,
        ]

    charts_table = Table(
        [[_box(sev_inner, "Flags by severity"), "", _box(rev_inner, "Reviewer decisions")]],
        colWidths=[chart_w, 16, chart_w],
        rowHeights=[120],
    )
    charts_table.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        
        # Left card styling
        ("BOX",   (0,0),(0,0), 0.5, BORDER_GRAY),
        ("BACKGROUND",(0,0),(0,0), BG_LIGHT),
        ("LEFTPADDING", (0,0),(0,0), 10),
        ("RIGHTPADDING",(0,0),(0,0), 10),
        ("TOPPADDING",  (0,0),(0,0), 10),
        ("BOTTOMPADDING",(0,0),(0,0), 10),

        # Right card styling
        ("BOX",   (2,0),(2,0), 0.5, BORDER_GRAY),
        ("BACKGROUND",(2,0),(2,0), BG_LIGHT),
        ("LEFTPADDING", (2,0),(2,0), 10),
        ("RIGHTPADDING",(2,0),(2,0), 10),
        ("TOPPADDING",  (2,0),(2,0), 10),
        ("BOTTOMPADDING",(2,0),(2,0), 10),
    ]))
    story.append(charts_table)
    story.append(Spacer(1, 12))

    # ── Flags by rule bar chart ───────────────────────────────────────────
    if rule_items:
        bar = HBarChart(rule_items, max_rule_count, content_w - 20)
        bar_box = Table([[_box(bar, "Flags by rule")]], colWidths=[content_w])
        bar_box.setStyle(TableStyle([
            ("BOX", (0,0),(0,0), 0.5, BORDER_GRAY),
            ("BACKGROUND",(0,0),(0,0), BG_LIGHT),
            ("LEFTPADDING",(0,0),(0,0), 10),
            ("RIGHTPADDING",(0,0),(0,0), 10),
            ("TOPPADDING",(0,0),(0,0), 10),
            ("BOTTOMPADDING",(0,0),(0,0), 10),
        ]))
        story.append(bar_box)
        story.append(Spacer(1, 12))

    # ── Totals summary row ────────────────────────────────────────────────
    totals_data = [[
        [Paragraph("TOTAL FLAGS",     styles["meta_label"]),
         Paragraph(str(total_flags),  styles["report_title"])],
        [Paragraph("RULES EVALUATED", styles["meta_label"]),
         Paragraph(str(len(rule_counts)), styles["report_title"])],
        [Paragraph("ACCEPTED",        styles["meta_label"]),
         Paragraph(str(accepted),     styles["report_title"])],
        [Paragraph("DISMISSED",       styles["meta_label"]),
         Paragraph(str(dismissed),    styles["report_title"])],
    ]]
    totals_t = Table(totals_data, colWidths=["25%","25%","25%","25%"])
    totals_t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LINEBEFORE",(1,0),(3,0),0.5,BORDER_GRAY),
        ("LEFTPADDING",(0,0),(-1,-1),10),
        ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    story.append(totals_t)
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY))
    story.append(Spacer(1, 8))

    # ── AI Disclaimer ─────────────────────────────────────────────────────
    disclaimer_text = (
        "<b>AI Disclaimer.</b> This report includes AI-assisted compliance analysis. "
        "Final approval decisions and comments reflect actions taken by authorized users "
        "within the ComplyCore workflow."
    )
    disclaimer_bg = Table(
        [[Paragraph(disclaimer_text, styles["disclaimer"])]],
        colWidths=[content_w],
    )
    disclaimer_bg.setStyle(TableStyle([
        ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
        ("BACKGROUND", (0,0),(0,0),   colors.HexColor("#EFF6FF")),
        ("BOX",        (0,0),(-1,-1), 0.5, BRAND_BLUE),
        ("LEFTPADDING",(0,0),(0,0),   8),
        ("RIGHTPADDING",(0,0),(0,0),  8),
        ("TOPPADDING",(0,0),(-1,-1),  6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
    ]))
    story.append(disclaimer_bg)

    # ════════════════════════════════════════════════════════════════════════
    # AUDIT TRAIL TABLE
    # ════════════════════════════════════════════════════════════════════════
    if audit_events:
        story.append(PageBreak())
        story.append(Paragraph("Audit Trail", styles["page_title"]))
        story.append(Paragraph(
            "A complete, timestamped record of every action — AI and human — taken on this document during review.",
            ParagraphStyle("at_sub", fontSize=8, textColor=TEXT_MUTED, fontName="Helvetica",
                           spaceBefore=0, spaceAfter=6, leading=12)))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY))
        story.append(Spacer(1, 6))

        header_style = ParagraphStyle("at_hdr", fontSize=7, fontName="Helvetica-Bold",
                                       textColor=TEXT_MUTED, spaceBefore=0, spaceAfter=0,
                                       tracking=0.5)
        event_title_style = ParagraphStyle("at_ev", fontSize=8.5, fontName="Helvetica-Bold",
                                            textColor=TEXT_DARK, spaceBefore=0, spaceAfter=1,
                                            leading=11)
        event_desc_style  = ParagraphStyle("at_desc", fontSize=7.5, fontName="Helvetica",
                                            textColor=TEXT_MUTED, spaceBefore=0, spaceAfter=0,
                                            leading=10)
        performer_style   = ParagraphStyle("at_perf", fontSize=8, fontName="Helvetica",
                                            textColor=TEXT_DARK, spaceBefore=0, spaceAfter=0,
                                            leading=11)
        ts_style          = ParagraphStyle("at_ts", fontSize=7.5, fontName="Helvetica",
                                            textColor=TEXT_MUTED, spaceBefore=0, spaceAfter=0,
                                            leading=11)

        col_w = [18, content_w - 18 - 100 - 90, 100, 90]

        table_data = [[
            Paragraph("#", header_style),
            Paragraph("EVENT", header_style),
            Paragraph("PERFORMED BY", header_style),
            Paragraph("TIMESTAMP", header_style),
        ]]

        grouped_audit_events = _group_audit_events(audit_events)

        for i, ev in enumerate(grouped_audit_events):
            label = _audit_label(ev)
            desc  = _audit_desc(ev)
            ts    = _fmt_audit_ts(ev, timezone_str=user_timezone)
            perf  = _audit_performer(ev)
            is_ai = bool(ev.get("is_ai"))

            t = (ev.get("event_type") or "").lower()
            is_approval  = t in ("approve_and_lock","approve","document_locked","document_published","publish")
            is_rejection = t in ("reject",) or "failed" in t

            if is_approval:
                ev_color = ACCEPT_COLOR
            elif is_rejection:
                ev_color = HIGH_COLOR
            else:
                ev_color = TEXT_DARK

            event_cell = [Paragraph(f'<font color="#{ev_color.hexval()[2:].upper()}">{label}</font>',
                                     event_title_style)]
            if desc:
                event_cell.append(Paragraph(desc, event_desc_style))

            if "grouped_events" in ev and len(ev["grouped_events"]) > 0:
                event_cell.append(Spacer(1, 4))
                import json
                
                groups = {}
                fallback_idx = 0
                for child in ev["grouped_events"]:
                    f = child.get("finding") or {}
                    chash = str(f.get("canonical_claim_hash") or "").strip()
                    cid   = str(f.get("claim_id") or "").strip()
                    ctxt  = str(f.get("claim_text") or f.get("finding_title") or f.get("finding_id") or "").strip()[:200]
                    
                    if chash:
                        gkey = f"h:{chash}"
                    elif cid:
                        gkey = f"cid:{cid}"
                    elif ctxt:
                        gkey = f"txt:{ctxt}"
                    else:
                        gkey = f"fallback:{fallback_idx}"
                        fallback_idx += 1
                        
                    code = None
                    if f and isinstance(f, dict):
                        code = f.get("finding_code")
                    if not code:
                        d_val = child.get("details")
                        if d_val:
                            if isinstance(d_val, str):
                                try:
                                    d = json.loads(d_val)
                                except Exception:
                                    d = {}
                            else:
                                d = d_val
                            code = d.get("finding_code")
                            
                    if code:
                        if gkey not in groups:
                            groups[gkey] = []
                        if str(code) not in groups[gkey]:
                            groups[gkey].append(str(code))
                
                pill_data = []
                for gkey, codes in groups.items():
                    if codes:
                        pill_data.append(", ".join(codes))

                if pill_data:
                    pill_tables = []
                    for p in pill_data:
                        t_pill = Table([[p]], rowHeights=[14])
                        t_pill.setStyle(TableStyle([
                            ("BACKGROUND", (0,0), (0,0), colors.HexColor("#F1F5F9")),
                            ("BOX", (0,0), (0,0), 0.5, colors.HexColor("#E2E8F0")),
                            ("LEFTPADDING", (0,0), (0,0), 4),
                            ("RIGHTPADDING", (0,0), (0,0), 4),
                            ("TOPPADDING", (0,0), (0,0), 2),
                            ("BOTTOMPADDING", (0,0), (0,0), 2),
                            ("ROUNDEDCORNERS", [3,3,3,3]),
                            ("FONTNAME", (0,0), (0,0), "Helvetica-Bold"),
                            ("FONTSIZE", (0,0), (0,0), 6.5),
                            ("TEXTCOLOR", (0,0), (0,0), colors.HexColor("#334155")),
                            ("ALIGN", (0,0), (0,0), "CENTER"),
                            ("VALIGN", (0,0), (0,0), "MIDDLE"),
                        ]))
                        pill_tables.append(t_pill)
                    
                    max_pills_per_row = 1
                    rows = []
                    for k in range(0, len(pill_tables), max_pills_per_row):
                        chunk = pill_tables[k:k+max_pills_per_row]
                        # Pad chunk with empty strings so Table does not crash
                        while len(chunk) < max_pills_per_row:
                            chunk.append("")
                        rows.append(chunk)
                    
                    pills_container = Table(rows, hAlign='LEFT', spaceBefore=0, spaceAfter=0)
                    pills_container.setStyle(TableStyle([
                        ("LEFTPADDING", (0,0), (-1,-1), 0),
                        ("RIGHTPADDING", (0,0), (-1,-1), 4),
                        ("TOPPADDING", (0,0), (-1,-1), 2),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
                    ]))
                    event_cell.append(pills_container)

            perf_parts = perf.split("\n", 1)
            perf_cell_content = perf_parts[0]
            if is_ai:
                perf_cell_content += ' <font color="#6D28D9"><b>[AI]</b></font>'
            perf_cell = [Paragraph(perf_cell_content, performer_style)]
            if len(perf_parts) > 1:
                perf_cell.append(Paragraph(perf_parts[1], event_desc_style))

            row_bg = BG_LIGHT if i % 2 == 0 else colors.white

            table_data.append([
                Paragraph(str(i + 1), ParagraphStyle("atnum", fontSize=8, textColor=TEXT_MUTED,
                                                       fontName="Helvetica", spaceBefore=0, spaceAfter=0)),
                event_cell,
                perf_cell,
                Paragraph(ts, ts_style),
            ])

        at = Table(table_data, colWidths=col_w, repeatRows=1)
        row_styles = [
            ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,0),  7),
            ("TEXTCOLOR",     (0,0),(-1,0),  TEXT_MUTED),
            ("BACKGROUND",    (0,0),(-1,0),  BG_LIGHT),
            ("LINEBELOW",     (0,0),(-1,0),  0.5, BORDER_GRAY),
            ("VALIGN",        (0,0),(-1,-1), "TOP"),
            ("LEFTPADDING",   (0,0),(-1,-1), 4),
            ("RIGHTPADDING",  (0,0),(-1,-1), 4),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ]
        # alternating row bg
        for row_i in range(1, len(table_data)):
            bg = BG_LIGHT if row_i % 2 == 0 else colors.white
            row_styles.append(("BACKGROUND", (0,row_i),(-1,row_i), bg))
            row_styles.append(("LINEBELOW", (0,row_i),(-1,row_i), 0.3, BORDER_GRAY))

        at.setStyle(TableStyle(row_styles))
        story.append(at)

    # ════════════════════════════════════════════════════════════════════════
    # AI FINDINGS DETAIL PAGES
    # ════════════════════════════════════════════════════════════════════════
    if findings:
        story.append(PageBreak())
        story.append(Paragraph("AI Finding Details", styles["page_title"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY))
        story.append(Spacer(1, 8))

        # ── Group by claim_id, canonical_claim_hash, or claim_text fallback ──────
        findings_by_claim = {}
        for f in findings:
            canonical_hash = str(f.get("canonical_claim_hash") or "").strip()
            claim_id = str(f.get("claim_id") or "").strip()
            claim_text = str(f.get("claim_text") or f.get("title") or f.get("id") or "").strip()[:200]
            
            if canonical_hash:
                fallback_key = f"h:{canonical_hash}"
            elif claim_id:
                fallback_key = f"cid:{claim_id}"
            else:
                fallback_key = f"txt:{claim_text}"
                
            if fallback_key not in findings_by_claim:
                findings_by_claim[fallback_key] = []
            findings_by_claim[fallback_key].append(f)

        def _get_sort_key(item):
            # item is (claim_key, claim_findings)
            for f in item[1]:
                loc = f.get("location") or ""
                import re
                pm = re.search(r"Page\s+(\d+)", loc, re.IGNORECASE)
                lm = re.search(r"Line\s+(\d+)", loc, re.IGNORECASE)
                p = int(pm.group(1)) if pm else (f.get("page_no") or 999999)
                l = int(lm.group(1)) if lm else (f.get("line_no") or 999999)
                if p != 999999 or l != 999999:
                    return (p, l)
            return (999999, 999999)

        sorted_claims = sorted(findings_by_claim.items(), key=_get_sort_key)

        idx = 1
        for claim_key, claim_findings in sorted_claims:
            first_finding = claim_findings[0]
            claim = _safe(first_finding.get("claim_text") or "", 400)
            title = _safe(first_finding.get("title") or "Untitled finding", 120)
            
            # Aggregate severities
            severities = [str(f.get("risk_level") or "LOW").upper() for f in claim_findings]
            severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
            highest_severity = "LOW"
            for s in severities:
                if severity_order.get(s, 1) > severity_order.get(highest_severity, 1):
                    highest_severity = s
                    
            if highest_severity == "HIGH":
                risk_color = HIGH_COLOR
            elif highest_severity == "MEDIUM":
                risk_color = MED_COLOR
            else:
                risk_color = LOW_COLOR

            # Aggregate status
            statuses = [str(f.get("status") or "pending").lower() for f in claim_findings]
            if "accepted" in statuses:
                group_status = "Accepted by Compliance"
            elif "rejected" in statuses:
                group_status = "Rejected"
            elif "dismissed" in statuses:
                group_status = "Dismissed"
            else:
                group_status = "Pending"

            # Aggregate rules and codes
            rules_list = []
            codes_list = []
            for f in claim_findings:
                code = _safe(f.get("finding_code") or f.get("code") or "")
                rule_code = _safe(f.get("rule_code") or "")
                rule = _safe(f.get("rule_name") or f.get("rule") or "")
                
                if not rule and rule_code:
                    key = rule_code.replace("RULE-", "").strip()
                    if key in rule_mapping:
                        rule = rule_mapping[key]
                if not rule and code.startswith("RULE-"):
                    parts = code.split("-")
                    if len(parts) >= 2 and parts[1] in rule_mapping:
                        rule = rule_mapping[parts[1]]
                if not rule and title and "Rule " in title:
                    try:
                        num = title.split("Rule ")[1].split(":")[0].strip()
                        if num in rule_mapping:
                            rule = rule_mapping[num]
                    except Exception:
                        pass
                
                if rule and rule not in rules_list:
                    rules_list.append(rule)
                if code and code not in codes_list:
                    codes_list.append(code)

            # extract location string for display
            loc_str = ""
            for f in claim_findings:
                if f.get("location"):
                    loc_val = str(f.get("location")).strip()
                    pm = re.search(r"Page\s+\d+", loc_val, re.IGNORECASE)
                    lm = re.search(r"Line\s+\d+", loc_val, re.IGNORECASE)
                    
                    if pm and lm:
                        loc_str = f"{pm.group(0)}, {lm.group(0)}"
                    elif pm:
                        loc_str = pm.group(0)
                    else:
                        loc_str = loc_val.split("·")[0].split("|")[0].split("-")[0].strip()
                    break

            loc_html = f" &nbsp;|&nbsp; <font color='#{TEXT_MUTED.hexval()[2:].upper()}'>{loc_str.title()}</font>" if loc_str else ""

            card_items = []
            inner_w = content_w - 24

            # Header strip (no title)
            header_data = [[
                Paragraph(f"<b>#{idx}</b> &nbsp; <font color='#{risk_color.hexval()[2:].upper()}'>{highest_severity}</font>{loc_html}",
                          ParagraphStyle("fh", fontSize=9, fontName="Helvetica-Bold",
                                         textColor=TEXT_DARK, leading=12,
                                         spaceBefore=0, spaceAfter=0))
            ]]
            header_t = Table(header_data, colWidths=[inner_w])
            header_t.setStyle(TableStyle([
                ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
                ("LEFTPADDING",(0,0),(-1,-1), 0),
                ("RIGHTPADDING",(0,0),(-1,-1),0),
                ("TOPPADDING",(0,0),(-1,-1),  0),
                ("BOTTOMPADDING",(0,0),(-1,-1),6),
                ("LINEBELOW",  (0,0),(-1,-1), 0.5, BORDER_GRAY),
            ]))
            card_items.append(header_t)

            # meta pill row
            meta_parts = []
            if codes_list: 
                meta_parts.append(f"Codes: <b>{', '.join(codes_list)}</b>")
            if meta_parts:
                card_items.append(Spacer(1, 4))
                card_items.append(Paragraph("  ·  ".join(meta_parts),
                    ParagraphStyle("fmeta", fontSize=7.5, textColor=TEXT_MUTED,
                                   fontName="Helvetica", spaceBefore=0, spaceAfter=0)))

            # claim
            if claim:
                card_items.append(Spacer(1, 6))
                card_items.append(Paragraph("<b>Claim:</b> " + claim, styles["finding_body"]))
            else:
                # description fallback
                desc = _safe(first_finding.get("description") or first_finding.get("summary") or "", 600)
                if desc:
                    card_items.append(Spacer(1, 4))
                    card_items.append(Paragraph(desc, styles["finding_body"]))

            # Rules violated
            if rules_list:
                card_items.append(Spacer(1, 6))
                card_items.append(Paragraph("<b>Rules Violated:</b>", ParagraphStyle("frv", fontSize=8, fontName="Helvetica-Bold", textColor=TEXT_DARK)))
                card_items.append(Spacer(1, 4))
                for rule in rules_list:
                    card_items.append(Paragraph(f"• {rule}", styles["finding_body"]))

            # Why risky & rationales
            why_texts = []
            for f in claim_findings:
                why = _safe(f.get("rationale") or f.get("why_risky") or "", 600)
                if why and why not in why_texts:
                    why_texts.append(why)
            
            if why_texts:
                card_items.append(Spacer(1, 6))
                why_combined = "<br/><br/>".join(why_texts)
                why_t = Table([[Paragraph(f"<b>▲ Why This Is Risky</b><br/>{why_combined}", styles["finding_body"])]],
                              colWidths=[inner_w])
                why_t.setStyle(TableStyle([
                    ("BACKGROUND",(0,0),(0,0), colors.HexColor("#FFF7ED")),
                    ("BOX",(0,0),(0,0), 0.5, colors.HexColor("#FED7AA")),
                    ("ROUNDEDCORNERS",(0,0),(-1,-1), [6, 6, 6, 6]),
                    ("LEFTPADDING",(0,0),(0,0), 8),("RIGHTPADDING",(0,0),(0,0),8),
                    ("TOPPADDING",(0,0),(0,0), 6),("BOTTOMPADDING",(0,0),(0,0),6),
                ]))
                card_items.append(why_t)

            # Suggestions
            accepted_sugg_id = None
            for f in claim_findings:
                if f.get("accepted_suggestion_id"):
                    accepted_sugg_id = f.get("accepted_suggestion_id")
                    break

            if "Accepted" in group_status and not accepted_sugg_id:
                ai_sugg = None
                for f in claim_findings:
                    if f.get("ai_suggestion"):
                        ai_sugg = f.get("ai_suggestion")
                        break
                if ai_sugg:
                    card_items.append(Spacer(1, 6))
                    sugg_t = Table([[Paragraph(f"<b>✓ Selected Alternative (AI)</b><br/>{ai_sugg}", styles["finding_body"])]],
                                   colWidths=[inner_w])
                    sugg_t.setStyle(TableStyle([
                        ("BACKGROUND",(0,0),(0,0), GREEN_BG),
                        ("BOX",(0,0),(0,0), 0.5, colors.HexColor("#BBF7D0")),
                        ("ROUNDEDCORNERS",(0,0),(-1,-1), [6, 6, 6, 6]),
                        ("LEFTPADDING",(0,0),(0,0), 8),("RIGHTPADDING",(0,0),(0,0),8),
                        ("TOPPADDING",(0,0),(0,0), 6),("BOTTOMPADDING",(0,0),(0,0),6),
                    ]))
                    card_items.append(sugg_t)
            elif "Accepted" not in group_status:
                for f in claim_findings:
                    ai_sugg = _safe(f.get("ai_suggestion") or "")
                    if ai_sugg:
                        card_items.append(Spacer(1, 6))
                        sugg_t = Table([[Paragraph(f"<b>AI Suggested Alternative</b><br/>{ai_sugg}", styles["finding_body"])]],
                                       colWidths=[inner_w])
                        sugg_t.setStyle(TableStyle([
                            ("BACKGROUND",(0,0),(0,0), colors.white),
                            ("BOX",(0,0),(0,0), 0.5, BORDER_GRAY),
                            ("ROUNDEDCORNERS",(0,0),(-1,-1), [6, 6, 6, 6]),
                            ("LEFTPADDING",(0,0),(0,0), 8),("RIGHTPADDING",(0,0),(0,0),8),
                            ("TOPPADDING",(0,0),(0,0), 6),("BOTTOMPADDING",(0,0),(0,0),6),
                        ]))
                        card_items.append(sugg_t)
                        break

            # Print Marketing/Manual suggestions
            for f in claim_findings:
                suggestions = f.get("suggestions", [])
                for s in suggestions:
                    s_text = _safe(s.get("text"))
                    s_author = _safe(s.get("author_name") or "User")
                    is_selected = str(s.get("id")) == str(accepted_sugg_id)
                    
                    if not is_selected and "Accepted" in group_status:
                        continue

                    card_items.append(Spacer(1, 6))
                    s_label = f"<b>✓ Selected Alternative ({s_author})</b><br/>" if is_selected else f"<b>Alternate Suggestion ({s_author})</b><br/>"
                    bg = GREEN_BG if is_selected else colors.white
                    bc = colors.HexColor("#BBF7D0") if is_selected else BORDER_GRAY

                    sugg_t = Table([[Paragraph(f"{s_label}{s_text}", styles["finding_body"])]],
                                   colWidths=[inner_w])
                    sugg_t.setStyle(TableStyle([
                        ("BACKGROUND",(0,0),(0,0), bg),
                        ("BOX",(0,0),(0,0), 0.5, bc),
                        ("ROUNDEDCORNERS",(0,0),(-1,-1), [6, 6, 6, 6]),
                        ("LEFTPADDING",(0,0),(0,0), 8),("RIGHTPADDING",(0,0),(0,0),8),
                        ("TOPPADDING",(0,0),(0,0), 6),("BOTTOMPADDING",(0,0),(0,0),6),
                    ]))
                    card_items.append(sugg_t)

            # Feedback Block
            all_comments_data = []
            all_comment_ids = set()
            for f in claim_findings:
                for c in f.get("comments", []):
                    c_id = c.get("id")
                    if c_id not in all_comment_ids:
                        all_comment_ids.add(c_id)
                        all_comments_data.append(c)

            if all_comments_data:
                card_items.append(Spacer(1, 6))
                feedback_texts = []
                for c in all_comments_data:
                    author = _safe(c.get("author_name") or "Unknown")
                    content = _safe(c.get("content"), 600)
                    feedback_texts.append(f"<b>{author}:</b> {content}")
                
                feedback_combined = "<br/>".join(feedback_texts)
                
                from reportlab.graphics.shapes import Drawing, Path
                msg_icon = Drawing(12, 12)
                p = Path(strokeColor=colors.HexColor("#D97A1F"), strokeWidth=1.2, fillColor=None, strokeLineCap=1, strokeLineJoin=1)
                p.moveTo(4, 3)
                p.lineTo(1.5, 3)
                p.lineTo(1.5, 10.5)
                p.lineTo(10.5, 10.5)
                p.lineTo(10.5, 3)
                p.lineTo(6, 3)
                p.lineTo(2, 0)
                p.lineTo(4, 3)
                msg_icon.add(p)
                
                header_t = Table([[msg_icon, Paragraph("<b><font color='#D97A1F'>Feedback</font></b>", ParagraphStyle("fh_fb", fontSize=8, fontName="Helvetica-Bold", textColor=colors.HexColor("#D97A1F")))]], colWidths=[16, inner_w-16-16])
                header_t.setStyle(TableStyle([
                    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                    ("LEFTPADDING", (0,0), (-1,-1), 0),
                    ("RIGHTPADDING", (0,0), (-1,-1), 0),
                    ("TOPPADDING", (0,0), (-1,-1), 0),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 0),
                ]))
                
                feedback_t = Table([[header_t], [Paragraph(feedback_combined, styles["finding_body"])]],
                                   colWidths=[inner_w])
                feedback_t.setStyle(TableStyle([
                    ("BACKGROUND",(0,0),(-1,-1), colors.HexColor("#FDF3E8")),
                    ("BOX",(0,0),(-1,-1), 0.5, colors.HexColor("#F3DDC2")),
                    ("ROUNDEDCORNERS",(0,0),(-1,-1), [6, 6, 6, 6]),
                    ("LEFTPADDING",(0,0),(-1,-1), 8),
                    ("RIGHTPADDING",(0,0),(-1,-1),8),
                    ("TOPPADDING",(0,0),(-1,0), 6),
                    ("BOTTOMPADDING",(0,-1),(-1,-1), 6),
                    ("BOTTOMPADDING",(0,0),(-1,0), 2),
                    ("TOPPADDING",(0,1),(-1,1), 2),
                ]))
                card_items.append(feedback_t)

            # Status Block
            if group_status != "Pending":
                card_items.append(Spacer(1, 6))
                if group_status == "Accepted by Compliance":
                    bg_color = GREEN_BG
                    border_color = GREEN_BORDER
                    status_text = "<b>Status: Accepted by compliance</b>"
                elif group_status == "Rejected":
                    bg_color = RED_BG
                    border_color = RED_BORDER
                    status_text = "<b>Status: Rejected by compliance</b>"
                    reason = None
                    for f in claim_findings:
                        if f.get("reject_reason"):
                            reason = _safe(f.get("reject_reason"), 600)
                            break
                    if reason:
                        status_text += f"<br/><b>Reason:</b> {reason}"
                elif group_status == "Dismissed":
                    bg_color = colors.HexColor("#F3F4F6")
                    border_color = colors.HexColor("#D1D5DB")
                    status_text = "<b>Status: Dismissed by compliance</b>"
                    reason = None
                    for f in claim_findings:
                        if f.get("dismissal_reason"):
                            reason = _safe(f.get("dismissal_reason"), 600)
                            break
                    if reason:
                        status_text += f"<br/><b>Reason:</b> {reason}"
                        
                status_t = Table([[Paragraph(status_text, styles["finding_body"])]],
                               colWidths=[inner_w])
                status_t.setStyle(TableStyle([
                    ("BACKGROUND",(0,0),(0,0), bg_color),
                    ("BOX",(0,0),(0,0), 0.5, border_color),
                    ("ROUNDEDCORNERS",(0,0),(-1,-1), [6, 6, 6, 6]),
                    ("LEFTPADDING",(0,0),(0,0), 8),("RIGHTPADDING",(0,0),(0,0),8),
                    ("TOPPADDING",(0,0),(0,0), 6),("BOTTOMPADDING",(0,0),(0,0),6),
                ]))
                card_items.append(status_t)

            finding_items = []

            # Wrap card in outer table
            outer_table = Table([[card_items]], colWidths=[content_w])
            outer_table.setStyle(TableStyle([
                ("BOX", (0,0), (-1,-1), 0.5, BORDER_GRAY),
                ("ROUNDEDCORNERS", (0,0), (-1,-1), [8, 8, 8, 8]),
                ("LEFTPADDING", (0,0), (-1,-1), 12),
                ("RIGHTPADDING", (0,0), (-1,-1), 12),
                ("TOPPADDING", (0,0), (-1,-1), 12),
                ("BOTTOMPADDING", (0,0), (-1,-1), 12),
            ]))
            
            finding_items.append(outer_table)

            finding_items.append(Spacer(1, 16))
            story.append(KeepTogether(finding_items))
            
            idx += 1

    # ── Build ─────────────────────────────────────────────────────────────
    doc.build(story)
    return buf.getvalue()
