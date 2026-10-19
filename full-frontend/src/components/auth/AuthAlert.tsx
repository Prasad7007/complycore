import * as React from "react"
import { AlertCircle, Info } from "lucide-react"
import { cn } from "@/lib/utils"

type AuthAlertProps = {
  variant?: "error" | "info"
  title?: string
  children: React.ReactNode
  className?: string
}

export function AuthAlert({
  variant = "error",
  title,
  children,
  className,
}: AuthAlertProps) {
  const isError = variant === "error"
  return (
    <div
      role={isError ? "alert" : "status"}
      className={cn(
        "flex gap-2.5 rounded-lg border px-3 py-2.5 text-sm leading-relaxed",
        isError
          ? "border-destructive/50 bg-destructive/10 text-destructive"
          : "border-border bg-muted/50 text-muted-foreground",
        className,
      )}
    >
      {isError ? (
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      ) : (
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-foreground/70" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        {title ? (
          <p className={cn("mb-1 font-semibold", isError ? "text-destructive" : "text-foreground")}>
            {title}
          </p>
        ) : null}
        <div className={cn(!isError && "text-foreground/90")}>{children}</div>
      </div>
    </div>
  )
}
