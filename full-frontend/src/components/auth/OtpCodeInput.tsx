import { useEffect, useMemo, useRef, useState } from "react"
import { Input } from "@/components/ui/input"

export function OtpCodeInput({
  length = 6,
  onComplete,
  onChange,
}: {
  length?: number
  onComplete?: (value: string) => void
  onChange?: (value: string) => void
}) {
  const [value, setValue] = useState<string[]>(Array.from({ length }, () => ""))
  const refs = useRef<Array<HTMLInputElement | null>>(Array.from({ length }, () => null))

  const otp = useMemo(() => value.join(""), [value])

  useEffect(() => {
    onChange?.(otp)
    if (otp.length === length && !value.includes("")) {
      onComplete?.(otp)
    }
  }, [otp, length, value, onComplete, onChange])

  return (
    <div className="flex w-full justify-between">
      {value.map((v, i) => (
        <Input
          key={i}
          ref={(el) => {
            refs.current[i] = el
          }}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          maxLength={1}
          value={v}
          onChange={(e) => {
            const next = e.target.value.replace(/\D/g, "").slice(-1)
            setValue((prev) => {
              const copy = [...prev]
              copy[i] = next
              return copy
            })
            if (next && i < length - 1) {
              refs.current[i + 1]?.focus()
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Backspace") {
              if (value[i]) {
                setValue((prev) => {
                  const copy = [...prev]
                  copy[i] = ""
                  return copy
                })
                return
              }
              if (i > 0) refs.current[i - 1]?.focus()
            }

            if (e.key === "ArrowLeft" && i > 0)
              refs.current[i - 1]?.focus()

            if (e.key === "ArrowRight" && i < length - 1)
              refs.current[i + 1]?.focus()
          }}
          onPaste={(e) => {
            const text = e.clipboardData
              .getData("text")
              .replace(/\D/g, "")

            if (!text) return
            e.preventDefault()

            const chars = text.slice(0, length).split("")

            setValue(() =>
              Array.from({ length }, (_, idx) => chars[idx] ?? "")
            )

            refs.current[Math.min(chars.length - 1, length - 1)]?.focus()
          }}
          className="h-12 w-12 rounded-lg bg-white text-center text-base"
        />
      ))}
    </div>
  )
}