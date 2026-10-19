import { cn } from "@/lib/utils"

export type ScanningInProgressProps = {
  /** Progress 0-100 */
  progress?: number
  /** Current backend-driven stage label */
  stageLabel?: string
  /** Optional rules progress label */
  rulesProgressLabel?: string
  /** Called when collapse is clicked */
  onCollapseClick?: () => void
  className?: string
}

const STAGE_STEPS = [
  { key: "parsing", label: "Parsing Document", range: [0, 15] },
  { key: "classifying", label: "Extracting Text", range: [15, 30] },
  { key: "analysis", label: "Performing AI Analysis", range: [30, 80] },
  { key: "consolidating", label: "Consolidating Result", range: [80, 100] },
] as const

export function ScanningInProgress({
  progress = 60,
  stageLabel,
  rulesProgressLabel,
  onCollapseClick,
  className,
}: ScanningInProgressProps) {
  const activeStepIdx = STAGE_STEPS.findIndex(
    (s) => progress >= s.range[0] && progress < s.range[1]
  )
  const resolvedIdx = activeStepIdx === -1 ? STAGE_STEPS.length - 1 : activeStepIdx

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      {/* Header */}
      <div className="flex items-center justify-between gap-3 pb-3">
        <span className="text-sm font-semibold text-foreground">AI Compliance Analysis</span>
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
          <img src="/documents/collapsibleIcon.svg" alt="" className="h-6 w-6 shrink-0 dark:invert dark:opacity-90" width={24} height={24} />
        )}
      </div>

      {/* Scanning content */}
      <div className="flex flex-1 flex-col items-center justify-center gap-6 py-8">
        <div className="relative">
          <img
            src="/documents/aiAnalysisFIleProgress.svg"
            alt="Document scanning"
            className="h-[98px] w-[84px]"
          />
        </div>

        {/* Progress bar */}
        <div className="w-full max-w-[327px] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">{stageLabel || "Scanning in progress"}</span>
            <span className="rounded-md bg-[#174199] px-2 py-0.5 text-xs font-medium text-white">
              {Math.round(progress)}%
            </span>
          </div>
          {rulesProgressLabel ? (
            <p className="text-xs text-muted-foreground">{rulesProgressLabel}</p>
          ) : null}
          <div
            className="h-[9px] w-full overflow-hidden rounded-[40px] bg-[#E5E7EB]"
            style={{ width: "327px", maxWidth: "100%" }}
          >
            <div
              className="h-full rounded-[40px] transition-all duration-1000 ease-out"
              style={{
                width: `${Math.min(100, Math.max(0, progress))}%`,
                background: "linear-gradient(90deg, #128BDA 0%, #7C3AED 100%)",
                boxShadow: progress < 100 ? "0 0 8px rgba(18, 139, 218, 0.5)" : "none",
              }}
            />
          </div>

          {/* Stage steps below bar */}
          <div className="mt-3 flex flex-col gap-1.5">
            {STAGE_STEPS.map((step, idx) => {
              const isDone = progress >= step.range[1]
              const isActive = idx === resolvedIdx
              return (
                <div key={step.key} className="flex items-center gap-2">
                  <div
                    className={cn(
                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold transition-colors duration-500",
                      isDone
                        ? "bg-[#128BDA] text-white"
                        : isActive
                          ? "border-2 border-[#128BDA] text-[#128BDA]"
                          : "border border-gray-300 text-gray-400"
                    )}
                  >
                    {isDone ? "✓" : idx + 1}
                  </div>
                  <span
                    className={cn(
                      "text-xs transition-colors duration-500",
                      isDone
                        ? "font-medium text-[#128BDA]"
                        : isActive
                          ? "font-medium text-foreground"
                          : "text-muted-foreground"
                    )}
                  >
                    {step.label}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
