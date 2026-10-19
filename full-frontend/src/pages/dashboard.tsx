import * as React from "react"
import { Navigate, useNavigate, useParams } from "react-router-dom"

import { MainLayout } from "@/components/layout/MainLayout"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RecentItemsTable } from "@/components/dashboard/RecentItemsTable"
import {
  auditApi,
  notificationsApi,
  usersApi,
  type DashboardStatCard,
  type DashboardStatCardsResponse,
  type NotificationItem,
  type ReviewStatusStats,
  type StatCardSeries,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  ChevronRight,
  ChevronDown,
  TrendingDown,
  TrendingUp,
  TriangleAlertIcon,
  CheckCircle2,
  MessageSquare,
  AtSign,
  Info,
} from "lucide-react"
import { FileIcon } from "@/components/icons/FileIcon"
type StatCardProps = {
  title: string
  value: string
  unit?: string
  description?: string
  info?: { title: string; desc: string; calc: string } | null
  trend?: string
  trendDirection?: "up" | "down" | "neutral"
  series?: StatCardSeries | null
  chartColorClass?: string
  valueClassName?: string
  rightIcon?: React.ReactNode
  className?: string
}

type TooltipPlacement = "above" | "below"

type SparkBar = { height: number; active: boolean; label: string; value: number }

const FALLBACK_BAR_COUNT = 12

function buildSparkBars(series: StatCardSeries | null | undefined): SparkBar[] {
  const points = series?.points ?? []
  if (!points.length) return []
  const max = points.reduce((m, p) => (p.value > m ? p.value : m), 0)
  const safeMax = max > 0 ? max : 1
  const recentThreshold = Math.max(0, points.length - 3)
  return points.map((p, idx) => {
    const ratio = p.value / safeMax
    const visualRatio = max <= 0 ? 0.05 : Math.max(0.06, Math.min(1, ratio))
    return {
      height: Math.round(visualRatio * 100),
      active: idx >= recentThreshold,
      label: p.label,
      value: p.value,
    }
  })
}

function StatCard({
  title,
  value,
  unit,
  description,
  info,
  trend,
  trendDirection,
  series,
  chartColorClass,
  valueClassName,
  rightIcon,
  className,
}: StatCardProps) {
  const trimmedTrend = trend?.trim()
  const isNegative = trendDirection === "down" || (trendDirection === undefined && (trimmedTrend?.startsWith("-") ?? false))
  const isPositive = trendDirection === "up" || (trendDirection === undefined && Boolean(trimmedTrend) && !isNegative)
  const TrendIcon = isNegative ? TrendingDown : TrendingUp
  const infoBtnRef = React.useRef<HTMLButtonElement | null>(null)
  const [tooltipOpen, setTooltipOpen] = React.useState(false)
  const [displayValue, setDisplayValue] = React.useState(value)
  const [barsReady, setBarsReady] = React.useState(false)
  const [hoveredBar, setHoveredBar] = React.useState<number | null>(null)
  const [tooltipPlacement, setTooltipPlacement] = React.useState<TooltipPlacement>("above")
  const [tooltipPos, setTooltipPos] = React.useState<{ left: number; top: number; maxWidth: number }>({
    left: 8,
    top: 8,
    maxWidth: 360,
  })

  const positionTooltip = React.useCallback(() => {
    const rect = infoBtnRef.current?.getBoundingClientRect()
    if (!rect) return
    const viewportWidth = window.innerWidth || 0
    const viewportHeight = window.innerHeight || 0
    const gutter = 8
    const maxWidth = Math.min(384, viewportWidth - gutter * 2)
    let left = rect.left
    if (left + maxWidth > viewportWidth - gutter) {
      left = viewportWidth - maxWidth - gutter
    }
    if (left < gutter) left = gutter

    // Prefer above, fallback below when near top edge.
    const placeAbove = rect.top > 220
    const top = placeAbove ? rect.top - 8 : Math.min(viewportHeight - 8, rect.bottom + 8)

    setTooltipPlacement(placeAbove ? "above" : "below")
    setTooltipPos({ left, top, maxWidth })
  }, [])

  const seriesBars = React.useMemo(() => buildSparkBars(series), [series])
  const chartBars: SparkBar[] = seriesBars.length
    ? seriesBars
    : Array.from({ length: FALLBACK_BAR_COUNT }, (_, idx) => ({
        height: 0,
        active: idx >= FALLBACK_BAR_COUNT - 3,
        label: "",
        value: 0,
      }))

  React.useEffect(() => {
    const timeoutId = window.setTimeout(() => setBarsReady(true), 30)
    return () => {
      window.clearTimeout(timeoutId)
      setBarsReady(false)
    }
  }, [title, value, trimmedTrend, seriesBars.length])

  React.useEffect(() => {
    const raw = String(value ?? "").trim()
    const compact = raw.replace(/,/g, "")
    const numericMatch = compact.match(/^(-?\d+(?:\.\d+)?)(.*)$/)
    if (!numericMatch) {
      setDisplayValue(value)
      return
    }

    const target = Number.parseFloat(numericMatch[1])
    if (!Number.isFinite(target)) {
      setDisplayValue(value)
      return
    }

    const suffix = numericMatch[2] ?? ""
    const hasComma = raw.includes(",")
    const decimals = (numericMatch[1].split(".")[1] ?? "").length
    const duration = 900
    const startTime = performance.now()
    let rafId = 0

    const formatNumber = (n: number) => {
      if (decimals > 0) {
        const fixed = n.toFixed(decimals)
        const [intPart, fracPart] = fixed.split(".")
        const intFormatted = hasComma
          ? Number.parseInt(intPart, 10).toLocaleString()
          : intPart
        return `${intFormatted}.${fracPart}`
      }
      return hasComma ? Math.round(n).toLocaleString() : String(Math.round(n))
    }

    const tick = (now: number) => {
      const progress = Math.min(1, (now - startTime) / duration)
      const eased = 1 - Math.pow(1 - progress, 3)
      const next = target * eased
      setDisplayValue(`${formatNumber(next)}${suffix}`)
      if (progress < 1) rafId = window.requestAnimationFrame(tick)
    }

    rafId = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(rafId)
  }, [value])

  const chartToneClass = chartColorClass ?? "bg-sky-500"
  const trendBadgeClass = isPositive
    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400"
    : isNegative
      ? "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-400"
      : "bg-muted text-muted-foreground"

  return (
    <Card className={cn("group rounded-xl border bg-card transition-shadow duration-300 hover:shadow-lg", className)}>
      <CardContent
        className={cn(
          "relative p-5"
        )}
      >
        {info ? (
          <button
            type="button"
            ref={infoBtnRef}
            className="absolute right-5 top-5 z-10 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-background/90 text-muted-foreground hover:text-foreground"
            aria-label={`About ${title}`}
            onMouseEnter={() => {
              setTooltipOpen(true)
              requestAnimationFrame(positionTooltip)
            }}
            onMouseLeave={() => setTooltipOpen(false)}
            onFocus={() => {
              setTooltipOpen(true)
              requestAnimationFrame(positionTooltip)
            }}
            onBlur={() => setTooltipOpen(false)}
          >
            <Info className="h-3.5 w-3.5" />
          </button>
        ) : null}

        <div className="flex items-start justify-between gap-4">
          <div className={cn("min-w-0 flex-1", info ? "pr-8" : undefined)}>
            <div className="text-xs font-medium text-muted-foreground">{title}</div>
            {description ? (
              <div className="mt-1 text-[11px] text-muted-foreground/90">{description}</div>
            ) : null}

            <div className="mt-2 flex w-full items-end justify-between gap-3">
              <div
                className={cn(
                  "text-2xl font-semibold tracking-tight text-foreground",
                  valueClassName
                )}
              >
                {displayValue}
                {unit ? <span className="ml-1 text-sm font-medium text-muted-foreground">{unit}</span> : null}
              </div>

              {trimmedTrend ? (
                <div
                  className={cn(
                    "mb-0.5 inline-flex items-center justify-end gap-1 rounded-md px-1.5 py-0.5 text-right text-[11px] font-semibold",
                    trendBadgeClass
                  )}
                >
                  <TrendIcon className="h-3.5 w-3.5" />
                  {trimmedTrend}
                </div>
              ) : (
                <span />
              )}
            </div>
          </div>

          {rightIcon ? (
            <div className="grid h-9 w-9 place-items-center rounded-lg bg-card/60 dark:bg-muted/60">
              {rightIcon}
            </div>
          ) : null}
        </div>

        <div
          className="relative mt-4 flex h-12 items-end gap-[3px]"
          onMouseLeave={() => setHoveredBar(null)}
        >
          {chartBars.map((bar, idx) => (
            <div
              key={`${title}-bar-${idx}`}
              className={cn(
                "h-full flex-1 origin-bottom rounded-t-[3px] transition-[opacity,transform,height] duration-500 ease-out",
                chartToneClass,
                bar.active
                  ? "opacity-70 group-hover:opacity-90"
                  : "opacity-30 group-hover:opacity-50",
                hoveredBar === idx && "opacity-100"
              )}
              style={{
                height: barsReady ? `${bar.height}%` : "0%",
                transitionDelay: `${idx * 40}ms`,
              }}
              onMouseEnter={() => setHoveredBar(idx)}
              role={bar.label ? "img" : undefined}
              aria-label={bar.label ? `${bar.label}: ${bar.value}` : undefined}
            />
          ))}

          {hoveredBar !== null && chartBars[hoveredBar]?.label ? (
            <div
              className="pointer-events-none absolute -top-7 left-0 right-0 flex justify-center"
              aria-hidden
            >
              <div className="rounded-md border border-border bg-popover px-2 py-1 text-[10px] font-medium text-foreground shadow-md">
                <span className="text-muted-foreground">{chartBars[hoveredBar].label}: </span>
                {(() => {
                  const val = chartBars[hoveredBar].value;
                  if (Number.isInteger(val)) {
                    return val.toLocaleString();
                  }
                  if (val > 0 && val < 0.1) {
                    return val.toFixed(3);
                  }
                  return val.toFixed(1);
                })()}
              </div>
            </div>
          ) : null}
        </div>

        {seriesBars.length >= 2 ? (
          <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground/80">
            <span>{seriesBars[0].label}</span>
            {seriesBars.length >= 3 ? (
              <span className="text-muted-foreground/70">
                {seriesBars[Math.floor(seriesBars.length / 2)].label}
              </span>
            ) : null}
            <span>{seriesBars[seriesBars.length - 1].label}</span>
          </div>
        ) : null}
        {info && tooltipOpen ? (
          <div
            className={cn(
              "pointer-events-none fixed z-[100] rounded-lg border border-border bg-popover p-3 text-left shadow-xl",
              tooltipPlacement === "above" ? "-translate-y-full" : "translate-y-0"
            )}
            style={{
              left: tooltipPos.left,
              top: tooltipPos.top,
              maxWidth: tooltipPos.maxWidth,
            }}
          >
            <div className="text-xs font-semibold text-foreground">{info.title}</div>
            <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{info.desc}</div>
            <div className="mt-2 rounded-md bg-muted px-2 py-1.5 text-[11px] text-muted-foreground">
              <span className="font-medium text-foreground">Calculation:</span> {info.calc}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

type BadgeProps = {
  children: React.ReactNode
  variant?: "high" | "ok" | "warn"
}

function Badge({ children, variant = "ok" }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-lg border px-2 py-0.5 text-[11px] font-medium",
        variant === "high" && "border-red-200 bg-red-50 text-red-600 dark:border-red-600 dark:bg-red-950/50 dark:text-red-400",
        variant === "warn" && "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-600 dark:bg-amber-950/50 dark:text-amber-400",
        variant === "ok" && "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400"
      )}
    >
      {children}
    </span>
  )
}

type ReviewStatusFetchParams = {
  period: string
  dateFrom?: string
  dateTo?: string
} | null

function ReviewStatusChart({
  orgSlug,
  fetchParams,
  chartTab,
}: {
  orgSlug?: string
  fetchParams: ReviewStatusFetchParams
  chartTab: "documents" | "under_review"
}) {
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [counts, setCounts] = React.useState<ReviewStatusStats | null>(null)
  const [barsReady, setBarsReady] = React.useState(false)

  React.useEffect(() => {
    if (!orgSlug?.trim() || !fetchParams) {
      setLoading(false)
      setError(null)
      setCounts(null)
      return
    }
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await auditApi.getReviewStatusStats(orgSlug, fetchParams.period, {
          dateFrom: fetchParams.dateFrom,
          dateTo: fetchParams.dateTo,
        })
        if (cancelled) return
        setCounts(res)
      } catch (e: any) {
        if (cancelled) return
        setError(e?.message || "Failed to load review status")
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [orgSlug, fetchParams?.period, fetchParams?.dateFrom, fetchParams?.dateTo])

  React.useEffect(() => {
    setBarsReady(false)
    const timeoutId = window.setTimeout(() => setBarsReady(true), 40)
    return () => window.clearTimeout(timeoutId)
  }, [chartTab, counts?.totalDocuments, counts?.marketingReview, counts?.complianceReview, counts?.pendingSmeReview, counts?.approved, counts?.rejected, counts?.published, counts?.notStarted])

  const bars = React.useMemo(() => {
    const c = counts ?? {
      totalDocuments: 0,
      marketingReview: 0,
      complianceReview: 0,
      approved: 0,
      rejected: 0,
      pendingSmeReview: 0,
      published: 0,
      notStarted: 0,
    }

    if (chartTab === "documents") {
      const underReview =
        c.marketingReview + c.complianceReview + c.pendingSmeReview + c.notStarted
      return [
        { id: "under_review", label: "Under review", value: underReview, color: "#FF6B7A" },
        { id: "approved", label: "Approved", value: c.approved, color: "#38BDF8" },
        { id: "rejected", label: "Rejected", value: c.rejected, color: "#7C86FF" },
        { id: "published", label: "Published", value: c.published, color: "#A3E635" },
      ]
    }

    return [
      { id: "marketing_review", label: "Marketing", value: c.marketingReview, color: "#FF6B7A" },
      { id: "compliance_review", label: "Compliance", value: c.complianceReview, color: "#34D399" },
      { id: "sme_review", label: "SME", value: c.pendingSmeReview, color: "#FBBF24" },
    ]
  }, [counts, chartTab])

  const total = counts?.totalDocuments ?? 0
  const totalUnderReview = React.useMemo(() => {
    if (!counts) return 0
    return counts.marketingReview + counts.complianceReview + counts.pendingSmeReview
  }, [counts])

  const chartDenom = chartTab === "under_review" ? totalUnderReview : total

  const max = React.useMemo(() => {
    const cap = chartDenom > 0 ? chartDenom : Math.max(...bars.map((b) => b.value), 0, 1)
    return Math.max(1, cap)
  }, [bars, chartDenom])

  const ticks = React.useMemo(() => {
    const step = Math.ceil(max / 4)
    const t1 = Math.max(0, max - step)
    const t2 = Math.max(0, max - step * 2)
    const t3 = Math.max(0, max - step * 3)
    const raw = [max, t1, t2, t3, 0].map((t) => Math.round(t))
    return [...new Set(raw)].sort((a, b) => b - a)
  }, [max])

  const barGridClass = chartTab === "documents" ? "grid-cols-4" : "grid-cols-3"

  const hexToRgb = (hex: string) => {
    const h = hex.replace("#", "")
    const r = Number.parseInt(h.slice(0, 2), 16)
    const g = Number.parseInt(h.slice(2, 4), 16)
    const b = Number.parseInt(h.slice(4, 6), 16)
    return { r, g, b }
  }

  const barAreaHeight = 168
  const labelAreaHeight = 52
  const countRowHeight = 28
  const barWidthPx = chartTab === "documents" ? 40 : 44

  if (!fetchParams) {
    return (
      <div className="mt-6 rounded-lg border border-dashed border-border bg-muted/30 px-4 py-10 text-center text-sm text-muted-foreground">
        Select From and To dates, then click <span className="font-medium text-foreground">Apply range</span>.
      </div>
    )
  }

  return (
    <div className="mt-6">
      {loading ? (
        <div className="py-12 text-center text-xs text-muted-foreground">Loading review status…</div>
      ) : error ? (
        <div className="py-12 text-center text-xs text-destructive">{error}</div>
      ) : (
      <div className="grid grid-cols-[32px_1fr] gap-3">
        {/* Y axis = document count (0 … total) */}
        <div className="flex flex-col">
          <div className="h-4 pr-1 text-right text-[10px] leading-none text-muted-foreground">
            Docs
          </div>
          <div style={{ height: countRowHeight }} aria-hidden />
          <div className="relative" style={{ height: barAreaHeight }}>
            {ticks.map((t, i) => {
              const top = ((max - t) / max) * 100
              return (
                <div
                  key={`tick-y-${i}-${t}`}
                  className="absolute -translate-y-1/2 pr-1 text-right text-xs text-muted-foreground"
                  style={{ top: `${top}%` }}
                >
                  {t}
                </div>
              )
            })}
          </div>
          <div style={{ height: labelAreaHeight }} />
        </div>

        {/* Plot */}
        <div className="flex flex-col">
          <div className="h-4" aria-hidden />
          {/* value/total above each bar */}
          <div className={cn("grid gap-3 px-1 sm:gap-5", barGridClass)} style={{ height: countRowHeight }}>
            {bars.map((b, idx) => (
              <div key={`count-${idx}`} className="flex w-full flex-col items-center justify-end pb-1 text-center">
                <span className="text-xs font-semibold tabular-nums tracking-tight text-foreground">
                  {b.value}/{chartDenom || 0}
                </span>
              </div>
            ))}
          </div>
          {/* Plot area (bars start from 0 baseline) */}
          <div className="relative" style={{ height: barAreaHeight }}>
            {ticks.map((t, i) => {
              const top = ((max - t) / max) * 100
              return (
                <div
                  key={`tick-line-${i}-${t}`}
                  className={cn(
                    "absolute left-0 right-0 border-t",
                    t === 0 ? "border-foreground/20" : "border-foreground/10"
                  )}
                  style={{ top: `${top}%` }}
                />
              )
            })}

            <div className="absolute inset-x-0 bottom-0">
              <div className={cn("grid gap-3 px-1 sm:gap-5", barGridClass)}>
                {bars.map((b, idx) => {
                  // Y-axis = document count; light bar = full total (same height every column); dark = this bucket's share
                  const fillPct =
                    chartDenom > 0 ? Math.max(0, Math.min(1, b.value / chartDenom)) * 100 : 0
                  const { r, g, b: bb } = hexToRgb(b.color)

                  return (
                    <div key={`bar-${idx}`} className="group flex justify-center">
                      <div
                        className="relative overflow-hidden rounded-[14px]"
                        style={{ height: barAreaHeight, width: barWidthPx }}
                        title={`${b.value} of ${chartDenom} documents`}
                      >
                        {/* Total documents — full height (same every column); light base + faint category tint */}
                        <div
                          className="absolute inset-0 rounded-[14px] border border-border/50 bg-muted/60 transition-all duration-300 group-hover:bg-muted/70 dark:bg-muted/45 dark:group-hover:bg-muted/55"
                          aria-hidden
                        />
                        <div
                          className="absolute inset-0 rounded-[14px] transition-all duration-300 group-hover:brightness-110"
                          style={{ backgroundColor: `rgba(${r}, ${g}, ${bb}, 0.18)` }}
                          aria-hidden
                        />
                        {/* Performed count — dark fill, height = count/total of Y-axis (total docs) */}
                        <div
                          className={cn(
                            "absolute bottom-0 left-0 right-0 overflow-hidden transition-[height,background-color,filter,transform] duration-500 ease-in-out group-hover:brightness-110 group-hover:saturate-125 group-hover:scale-y-[1.02]",
                            fillPct >= 99.5 ? "rounded-[14px]" : "rounded-b-[14px] rounded-t-[6px]"
                          )}
                          style={{
                            height: barsReady ? `${fillPct}%` : "0%",
                            backgroundColor: `rgb(${r}, ${g}, ${bb})`,
                            transitionDelay: `${idx * 55}ms`,
                          }}
                        >
                          <div
                            className="pointer-events-none absolute inset-x-0 top-0 h-3 -translate-y-1 rounded-full opacity-50 blur-[1px] transition-all duration-500 group-hover:h-4 group-hover:opacity-80"
                            style={{
                              background: "linear-gradient(180deg, rgba(255,255,255,0.65) 0%, rgba(255,255,255,0.1) 80%, transparent 100%)",
                            }}
                            aria-hidden
                          />
                          <div
                            className="pointer-events-none absolute inset-0 translate-y-2 opacity-0 transition-all duration-500 group-hover:translate-y-0 group-hover:opacity-100"
                            style={{
                              background:
                                "linear-gradient(180deg, rgba(255,255,255,0.25) 0%, rgba(255,255,255,0.08) 30%, rgba(255,255,255,0) 70%)",
                            }}
                            aria-hidden
                          />
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Category labels below the 0 baseline */}
          <div
            className={cn("grid gap-3 px-1 sm:gap-5", barGridClass)}
            style={{ minHeight: labelAreaHeight }}
          >
            {bars.map((b, idx) => (
              <div
                key={`x-${idx}`}
                className="flex flex-col items-center justify-start gap-1.5 px-0.5 pt-2 text-center"
              >
                <div className="max-w-[5.5rem] text-xs font-medium leading-snug text-muted-foreground">
                  {b.label}
                </div>
                <span className="h-1 w-1 shrink-0 rounded-full bg-muted-foreground/35" aria-hidden />
              </div>
            ))}
          </div>

          <p className="mt-3 text-center text-xs text-muted-foreground">
            {chartTab === "under_review" ? (
              <>Total documents under review: {totalUnderReview}</>
            ) : (
              <>Total documents: {total}</>
            )}
            {chartTab === "documents" && counts && counts.notStarted > 0 ? (
              <span className="mt-1 block text-[11px] leading-snug">
                Under Review includes {counts.notStarted} document
                {counts.notStarted === 1 ? "" : "s"} without a started workflow.
              </span>
            ) : null}
          </p>
        </div>
      </div>
      )}
    </div>
  )
}

type ActivityPill = { label: string; tone?: "neutral" | "muted" }

type ActivityItem = {
  feedKey: string
  kind: string
  pills?: ActivityPill[]
  title: string
  description?: string
  ruleText?: string
  severity?: "high" | "warn" | "ok"
  icon?: React.ReactNode
  tone?: "danger" | "default" | "success" | "info" | "warning" | "mention"
  documentId?: string | null
  socialPostId?: string | null
}

function shortFeedTimestamp(iso: string): string {
  if (!iso) return ""
  const utcIso = iso.endsWith("Z") ? iso : iso + "Z"
  const d = new Date(utcIso)
  if (Number.isNaN(d.getTime())) return ""
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

function mapNotificationToActionItem(item: NotificationItem): ActivityItem {
  const when = shortFeedTimestamp(item.created_at)
  const pills: ActivityPill[] = []
  if (when) pills.push({ label: when, tone: "muted" })
  pills.unshift({ label: item.type.replace(/_/g, " "), tone: "muted" })

  let tone: ActivityItem["tone"] = "default"
  let icon = <FileIcon className="h-4 w-4 text-muted-foreground" />

  const t = item.type.toLowerCase()
  if (t.includes("approved") || t.includes("published") || t.includes("workflow")) {
    tone = "success"
    icon = <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-500" />
  } else if (t.includes("comment") || t.includes("discussion")) {
    tone = "info"
    icon = <MessageSquare className="h-4 w-4 text-sky-600 dark:text-sky-500" />
  } else if (t.includes("mention")) {
    tone = "mention"
    icon = <AtSign className="h-4 w-4 text-indigo-600 dark:text-indigo-500" />
  } else if (t.includes("reject") || t.includes("high_risk") || t.includes("needs_revision")) {
    tone = "danger"
    icon = <TriangleAlertIcon className="h-4 w-4 text-[#FF383C]" />
  }

  return {
    feedKey: `notification-${item.id}`,
    kind: "Action item",
    pills,
    title: item.title || "Notification",
    description: item.message || undefined,
    ruleText: undefined,
    severity: undefined,
    tone,
    icon,
    documentId: item.reference_type === "document" ? item.reference_id : null,
    socialPostId: null,
  }
}

function isWithinLastMonth(iso: string): boolean {
  if (!iso) return false
  const utcIso = iso.endsWith("Z") ? iso : iso + "Z"
  const createdAt = new Date(utcIso)
  if (Number.isNaN(createdAt.getTime())) return false
  const cutoff = Date.now() - 30 * 24 * 60 * 60 * 1000
  return createdAt.getTime() >= cutoff
}

function ActivityPillView({ pill }: { pill: ActivityPill }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-lg border px-2 py-0.5 text-[11px] font-medium",
        pill.tone === "muted"
          ? "border-foreground/10 bg-foreground/[0.03] text-muted-foreground"
          : "border-foreground/10 bg-card text-muted-foreground"
      )}
    >
      {pill.label}
    </span>
  )
}

type ReviewChartPreset = "week" | "month" | "ytd" | "custom"

function getStatsGridClass(role: string | undefined, cardCount: number): string {
  if (role === "marketing" && cardCount === 4) return "xl:grid-cols-2"
  if (role === "superadmin" && cardCount >= 5) return "xl:grid-cols-6"
  if (cardCount <= 1) return "xl:grid-cols-1"
  if (cardCount === 2) return "xl:grid-cols-2"
  if (cardCount === 3) return "xl:grid-cols-3"
  if (cardCount === 4) return "xl:grid-cols-4"
  return "xl:grid-cols-3"
}

function getStatsCardClass(role: string | undefined, idx: number): string | undefined {
  if (role === "superadmin") {
    if (idx < 2) return "min-h-[230px] xl:col-span-3"
    return "min-h-[190px] xl:col-span-2"
  }
  void idx
  return "min-h-[190px]"
}

export default function DashboardPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const navigate = useNavigate()
  const [reviewChartPreset, setReviewChartPreset] = React.useState<ReviewChartPreset>("month")
  const [reviewAppliedCustom, setReviewAppliedCustom] = React.useState<{ from: string; to: string } | null>(null)
  const [reviewCustomFrom, setReviewCustomFrom] = React.useState("")
  const [reviewCustomTo, setReviewCustomTo] = React.useState("")
  const [reviewChartTab, setReviewChartTab] = React.useState<"documents" | "under_review">("documents")
  const [reviewPeriodMenuOpen, setReviewPeriodMenuOpen] = React.useState(false)
  const reviewPeriodMenuRef = React.useRef<HTMLDivElement | null>(null)
  const reviewTabWrapRef = React.useRef<HTMLDivElement | null>(null)
  const reviewTabDocsRef = React.useRef<HTMLButtonElement | null>(null)
  const reviewTabUnderReviewRef = React.useRef<HTMLButtonElement | null>(null)
  const [reviewTabInk, setReviewTabInk] = React.useState({ x: 0, width: 0 })

  const reviewFetchParams = React.useMemo((): ReviewStatusFetchParams => {
    if (reviewChartPreset === "custom") {
      if (!reviewAppliedCustom) return null
      return {
        period: "custom",
        dateFrom: reviewAppliedCustom.from,
        dateTo: reviewAppliedCustom.to,
      }
    }
    return { period: reviewChartPreset }
  }, [reviewChartPreset, reviewAppliedCustom])

  React.useEffect(() => {
    if (!reviewPeriodMenuOpen) return
    const onDown = (e: MouseEvent) => {
      const el = reviewPeriodMenuRef.current
      if (el && !el.contains(e.target as Node)) setReviewPeriodMenuOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [reviewPeriodMenuOpen])

  React.useLayoutEffect(() => {
    const positionInk = () => {
      const wrap = reviewTabWrapRef.current
      const activeBtn =
        reviewChartTab === "documents" ? reviewTabDocsRef.current : reviewTabUnderReviewRef.current
      if (!wrap || !activeBtn) return
      const wrapRect = wrap.getBoundingClientRect()
      const btnRect = activeBtn.getBoundingClientRect()
      setReviewTabInk({
        x: btnRect.left - wrapRect.left,
        width: btnRect.width,
      })
    }

    positionInk()
    window.addEventListener("resize", positionInk)
    return () => window.removeEventListener("resize", positionInk)
  }, [reviewChartTab])

  const [searchQuery, setSearchQuery] = React.useState("")
  const [activityItems, setActivityItems] = React.useState<ActivityItem[]>([])
  const [activityLoading, setActivityLoading] = React.useState(true)
  const [activityError, setActivityError] = React.useState<string | null>(null)
  const [stats, setStats] = React.useState<DashboardStatCardsResponse | null>(null)
  const [statsLoading, setStatsLoading] = React.useState(true)
  const [statsError, setStatsError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    let eventSource: EventSource | null = null
    let reconnectTimer: number | undefined
    let reconnectDelay = 2000
    let fallbackPollTimer: number | undefined

    const stopFallbackPolling = () => {
      if (fallbackPollTimer) {
        window.clearInterval(fallbackPollTimer)
        fallbackPollTimer = undefined
      }
    }

    const startFallbackPolling = () => {
      stopFallbackPolling()
      fallbackPollTimer = window.setInterval(() => {
        void loadActionItems()
      }, 60000)
    }

    const connectNotificationsStream = () => {
      if (cancelled) return
      try {
        eventSource = new EventSource(notificationsApi.streamUrl(), { withCredentials: true })
        eventSource.onopen = () => {
          stopFallbackPolling()
          reconnectDelay = 2000
        }
        eventSource.onmessage = () => {
          void loadActionItems()
        }
        eventSource.onerror = () => {
          eventSource?.close()
          eventSource = null
          if (cancelled) return
          startFallbackPolling()
          reconnectDelay = Math.min(reconnectDelay * 2, 30000)
          reconnectTimer = window.setTimeout(connectNotificationsStream, reconnectDelay)
        }
      } catch {
        startFallbackPolling()
      }
    }

    const loadActionItems = async () => {
      setActivityLoading(true)
      setActivityError(null)
      try {
        const items = await notificationsApi.list()
        if (cancelled) return
        const lastMonthItems = (items || []).filter((n) => isWithinLastMonth(n.created_at))
        setActivityItems(lastMonthItems.map(mapNotificationToActionItem))
      } catch (e: any) {
        if (cancelled) return
        setActivityError(e?.message || "Failed to load action items")
        setActivityItems([])
      } finally {
        if (!cancelled) setActivityLoading(false)
      }
    }

    ;(async () => {
      if (!orgSlug?.trim()) {
        setStatsLoading(false)
        return
      }
      setStatsLoading(true)
      setStatsError(null)
      const roleRes = await Promise.resolve().then(() => usersApi.getMe())
        .then((value) => ({ status: "fulfilled", value } as const))
        .catch((reason) => ({ status: "rejected", reason } as const))
      if (cancelled) return
      const roleList: string[] =
        roleRes.status === "fulfilled" && Array.isArray((roleRes.value as any)?.roles)
          ? (roleRes.value as any).roles.map((r: unknown) => String(r).toLowerCase())
          : []
      const statRole: "marketing" | "sme" | "compliance" | "superadmin" = roleList.includes("super_admin")
        ? "superadmin"
        : roleList.includes("compliance")
          ? "compliance"
          : roleList.includes("marketing")
            ? "marketing"
            : "sme"
      const stRes = await Promise.resolve().then(() =>
        auditApi.getDashboardStatCards(orgSlug, statRole, "month")
      )
        .then((value) => ({ status: "fulfilled", value } as const))
        .catch((reason) => ({ status: "rejected", reason } as const))
      if (cancelled) return
      if (stRes.status === "fulfilled") {
        setStats(stRes.value)
        setStatsError(null)
      } else {
        setStats(null)
        setStatsError(
          stRes.reason instanceof Error ? stRes.reason.message : "Failed to load stats"
        )
      }
      setStatsLoading(false)
    })()
    void loadActionItems()
    connectNotificationsStream()
    return () => {
      cancelled = true
      eventSource?.close()
      stopFallbackPolling()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
  }, [orgSlug])

  const openActivityItem = React.useCallback(
    (item: ActivityItem) => {
      if (!orgSlug?.trim()) return
      if (item.documentId) {
        navigate(
          `/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${item.documentId}`
        )
        return
      }
      if (item.socialPostId) {
        navigate(
          `/orgs/${encodeURIComponent(orgSlug)}/social-media/detail/${encodeURIComponent(item.socialPostId)}`
        )
      }
    },
    [navigate, orgSlug]
  )

  if (!orgSlug?.trim()) {
    return <Navigate to="/pending-access" replace />
  }

  const cards: DashboardStatCard[] = stats?.cards ?? []
  const displayCards: Array<DashboardStatCard | null> = statsLoading
    ? Array.from({ length: 4 }, () => null)
    : cards
  const gridColsClass = getStatsGridClass(stats?.role, cards.length)
  const graphPalette = ["bg-blue-500", "bg-violet-500", "bg-emerald-500", "bg-amber-500", "bg-red-500", "bg-cyan-500"]

  return (
    <MainLayout
      header={{
        breadcrumbs: [
          { label: "ComplyCore", to: `/orgs/${encodeURIComponent(orgSlug)}/dashboard/default` },
          { label: "Dashboard" },
        ],
        searchQuery,
        onSearchChange: setSearchQuery,
        searchPlaceholder: "Search documents",
      }}
    >
      <div className="space-y-6">
        <div className={cn("grid grid-cols-1 gap-5 md:grid-cols-2", gridColsClass)}>
          {displayCards.map((card, idx) => (
            <StatCard
              key={statsLoading ? `loading-${idx}` : (card?.id ?? `card-${idx}`)}
              title={statsLoading ? "Loading…" : (card?.label ?? "—")}
              value={
                statsLoading
                  ? "…"
                  : statsError
                    ? "—"
                    : (card?.value ?? "—")
              }
              unit={statsLoading || statsError ? undefined : card?.unit ?? undefined}
              description={statsLoading || statsError ? undefined : card?.description}
              info={statsLoading || statsError ? null : card?.info ?? null}
              trend={
                !statsLoading && !statsError
                  ? card?.trend?.display ?? undefined
                  : undefined
              }
              trendDirection={
                !statsLoading && !statsError
                  ? card?.trend?.direction ?? undefined
                  : undefined
              }
              series={statsLoading || statsError ? null : card?.series ?? null}
              chartColorClass={graphPalette[idx % graphPalette.length]}
              className={cn(getStatsCardClass(stats?.role, idx))}
            />
          ))}
        </div>
        {statsError ? (
          <p className="text-center text-xs text-destructive" role="status">
            {statsError}
          </p>
        ) : null}

        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <Card className="rounded-xl border bg-card h-full">
            <CardContent className="p-6 h-full flex flex-col">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold text-foreground">Action Items</div>
                  {/*<div className="mt-1 text-xs text-muted-foreground">
                    User-relevant notifications, mentions, and workflow updates
                  </div>*/}
                </div>
              </div>

              {/* Fixed height to match adjacent chart, but fully scrollable */}
              <div className="activity-scroll mt-4 h-[360px] space-y-3 overflow-y-auto pr-2">
                {activityLoading ? (
                  <div className="py-8 text-center text-sm text-muted-foreground">Loading action items…</div>
                ) : activityError ? (
                  <div className="py-8 text-center text-sm text-destructive">{activityError}</div>
                ) : activityItems.length === 0 ? (
                  <div className="py-8 text-center text-sm text-muted-foreground">
                    No action items right now.
                  </div>
                ) : null}
                {!activityLoading &&
                  !activityError &&
                  activityItems.map((item) => {
                  const isDanger = item.tone === "danger"
                  const isSuccess = item.tone === "success"
                  const isInfo = item.tone === "info"
                  const isMention = item.tone === "mention"
                  const canOpen = Boolean(item.documentId || item.socialPostId)
                  
                  const containerClassName = cn(
                    "group w-full rounded-xl border p-4 text-left transition-colors",
                    isDanger && "border-red-200 bg-red-50/40 hover:bg-red-50/60 dark:border-red-800 dark:bg-red-950/40 dark:hover:bg-red-950/60",
                    isSuccess && "border-emerald-200 bg-emerald-50/40 hover:bg-emerald-50/60 dark:border-emerald-800 dark:bg-emerald-950/40 dark:hover:bg-emerald-950/60",
                    isInfo && "border-sky-200 bg-sky-50/40 hover:bg-sky-50/60 dark:border-sky-800 dark:bg-sky-950/40 dark:hover:bg-sky-950/60",
                    isMention && "border-indigo-200 bg-indigo-50/40 hover:bg-indigo-50/60 dark:border-indigo-800 dark:bg-indigo-950/40 dark:hover:bg-indigo-950/60",
                    (!isDanger && !isSuccess && !isInfo && !isMention) && "bg-card hover:bg-muted/50",
                    !canOpen && "cursor-default opacity-95"
                  )

                  return (
                    <button
                      key={item.feedKey}
                      type="button"
                      className={containerClassName}
                      aria-disabled={!canOpen}
                      onClick={() => canOpen && openActivityItem(item)}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            {item.icon ? (
                              <span className="mr-0.5 inline-flex items-center">{item.icon}</span>
                            ) : null}
                            <span className="text-xs font-medium text-muted-foreground">
                              {item.kind}
                            </span>
                            {item.pills?.length ? (
                              <span className="flex flex-wrap items-center gap-2">
                                {item.pills.map((p, pIdx) => (
                                  <ActivityPillView key={`${p.label}-${pIdx}`} pill={p} />
                                ))}
                              </span>
                            ) : null}
                          </div>

                          <div className="mt-1 text-sm font-semibold text-foreground">
                            {item.title}
                          </div>

                          {item.description ? (
                            <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                              {item.description}
                            </div>
                          ) : null}

                          {item.ruleText ? (
                            <div
                              className={cn(
                                "mt-2 text-xs",
                                isDanger ? "text-red-600" : "text-muted-foreground"
                              )}
                            >
                              {item.ruleText}
                            </div>
                          ) : null}
                        </div>

                        <div className="flex items-center gap-3">
                          {item.severity ? (
                            item.severity === "high" ? (
                              <Badge variant="high">High</Badge>
                            ) : item.severity === "warn" ? (
                              <Badge variant="warn">Medium</Badge>
                            ) : (
                              <Badge variant="ok">Approved</Badge>
                            )
                          ) : null}

                          <ChevronRight
                            className={cn(
                              "h-4 w-4 text-muted-foreground transition-colors",
                              canOpen && "group-hover:text-foreground"
                            )}
                          />
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-xl border border-border bg-white shadow-sm dark:bg-card">
            <CardContent className="p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="text-lg font-semibold text-foreground">Review Status</div>
                  <div
                    ref={reviewTabWrapRef}
                    className="relative mt-4 inline-flex items-stretch gap-8 border-b border-border/70"
                  >
                    <span
                      className="pointer-events-none absolute bottom-0 h-0.5 rounded-full bg-foreground transition-[transform,width] duration-300 ease-in-out"
                      style={{
                        width: `${reviewTabInk.width}px`,
                        transform: `translateX(${reviewTabInk.x}px)`,
                      }}
                      aria-hidden
                    />
                    <button
                      ref={reviewTabDocsRef}
                      type="button"
                      onClick={() => setReviewChartTab("documents")}
                      className={cn(
                        "pb-2.5 text-sm font-medium transition-colors duration-200",
                        reviewChartTab === "documents"
                          ? "text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Documents
                    </button>
                    <button
                      ref={reviewTabUnderReviewRef}
                      type="button"
                      onClick={() => setReviewChartTab("under_review")}
                      className={cn(
                        "pb-2.5 text-sm font-medium transition-colors duration-200",
                        reviewChartTab === "under_review"
                          ? "text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Under review
                    </button>
                  </div>
                </div>

                <div ref={reviewPeriodMenuRef} className="relative shrink-0 text-left sm:min-w-[260px]">
                  <button
                    type="button"
                    onClick={() => setReviewPeriodMenuOpen((o) => !o)}
                    className="flex w-full min-w-[160px] items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-2 text-sm text-muted-foreground shadow-sm hover:bg-muted/80 transition-all duration-200"
                    aria-expanded={reviewPeriodMenuOpen}
                    aria-haspopup="listbox"
                  >
                    <span className="truncate text-foreground">
                      {reviewChartPreset === "custom"
                        ? reviewAppliedCustom
                          ? `${reviewAppliedCustom.from} to ${reviewAppliedCustom.to}`
                          : "Custom range"
                        : reviewChartPreset === "ytd"
                          ? "Year to date"
                          : reviewChartPreset === "month"
                            ? "Month"
                            : "Week"}
                    </span>
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
                        reviewPeriodMenuOpen && "rotate-180"
                      )}
                      aria-hidden
                    />
                  </button>

                  <div
                    className={cn(
                      "absolute right-0 z-20 mt-2 w-[min(100vw-2rem,280px)] rounded-xl border border-border bg-card py-1 shadow-lg",
                      "origin-top-right transition-all duration-200",
                      reviewPeriodMenuOpen
                        ? "translate-y-0 scale-100 opacity-100 pointer-events-auto"
                        : "-translate-y-1 scale-95 opacity-0 pointer-events-none"
                    )}
                    role="listbox"
                  >
                    {(
                      [
                        { key: "week" as const, label: "Week" },
                        { key: "month" as const, label: "Month" },
                        { key: "ytd" as const, label: "Year to date" },
                      ] as const
                    ).map((opt) => (
                      <button
                        key={opt.key}
                        type="button"
                        role="option"
                        aria-selected={reviewChartPreset === opt.key}
                        className={cn(
                          "flex w-full items-center justify-between px-4 py-2.5 text-left text-sm hover:bg-muted transition-colors duration-150",
                          reviewChartPreset === opt.key && "bg-muted/60 font-medium text-foreground"
                        )}
                        onClick={() => {
                          setReviewChartPreset(opt.key)
                          setReviewAppliedCustom(null)
                          setReviewPeriodMenuOpen(false)
                        }}
                      >
                        {opt.label}
                      </button>
                    ))}
                    <div className="border-t border-border">
                      <button
                        type="button"
                        className={cn(
                          "flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left text-sm hover:bg-muted/80 transition-colors duration-150",
                          reviewChartPreset === "custom" && "bg-muted/50 dark:bg-muted/40"
                        )}
                        onClick={() => {
                          setReviewChartPreset("custom")
                          // Re-open inputs so user can change the applied custom range.
                          setReviewAppliedCustom(null)
                          setReviewPeriodMenuOpen(false)
                        }}
                      >
                        <span className="font-medium">Custom range</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {reviewChartPreset === "custom" && !reviewAppliedCustom ? (
                <div className="mt-4 rounded-xl border border-border bg-muted/25 p-4 dark:bg-muted/30">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="review-custom-from"
                        className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                      >
                        From
                      </Label>
                      <Input
                        id="review-custom-from"
                        type="date"
                        value={reviewCustomFrom}
                        onChange={(e) => setReviewCustomFrom(e.target.value)}
                        className="h-10"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="review-custom-to"
                        className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                      >
                        To
                      </Label>
                      <Input
                        id="review-custom-to"
                        type="date"
                        value={reviewCustomTo}
                        onChange={(e) => setReviewCustomTo(e.target.value)}
                        className="h-10"
                      />
                    </div>
                    <div className="flex items-end">
                      <Button
                        type="button"
                        className="h-10 w-full rounded-lg bg-foreground font-semibold text-background hover:bg-foreground/90"
                        onClick={() => {
                          if (!reviewCustomFrom.trim() || !reviewCustomTo.trim()) {
                            window.alert("Please choose both From and To dates.")
                            return
                          }
                          if (reviewCustomFrom > reviewCustomTo) {
                            window.alert("From date must be on or before To date.")
                            return
                          }
                          setReviewAppliedCustom({
                            from: reviewCustomFrom.trim(),
                            to: reviewCustomTo.trim(),
                          })
                        }}
                      >
                        Apply range
                      </Button>
                    </div>
                  </div>
                </div>
              ) : null}

              <ReviewStatusChart orgSlug={orgSlug} fetchParams={reviewFetchParams} chartTab={reviewChartTab} />
            </CardContent>
          </Card>
        </div>

        <RecentItemsTable orgSlug={orgSlug} searchQuery={searchQuery} />
      </div>
    </MainLayout>
  )
}
