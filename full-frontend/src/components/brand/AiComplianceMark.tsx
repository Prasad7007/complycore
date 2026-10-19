import { cn } from "@/lib/utils"

export function AiComplianceMark({ className }: { className?: string }) {
  return (
    <img
      src="/common/main-logo.svg"
      alt="AI Compliance Logo"
      className={cn("h-10 w-auto object-contain", className)}
    />
  )
}
