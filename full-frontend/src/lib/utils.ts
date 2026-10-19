import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDocumentType(
  type: string | null | undefined,
  status?: string | null
): string {
  if ((status || "").toLowerCase() === "skipped") return "Non-educational"
  if (!type) return "Unknown"
  const cleanType = type.toLowerCase()
  if (cleanType.includes("educational")) return "Educational"
  if (cleanType === "performance_related" || cleanType === "product_feature") return "Performance-related"
  if (cleanType === "client_communications") return "Client Communications"
  
  return cleanType.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}
