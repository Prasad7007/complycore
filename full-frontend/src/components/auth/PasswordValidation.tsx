interface PasswordValidationProps {
  password: string
  onlyShowInvalid?: boolean
}

interface ValidationRule {
  label: string
  isValid: boolean
}

export function PasswordValidation({ password, onlyShowInvalid = false }: PasswordValidationProps) {
  const rules: ValidationRule[] = [
    {
      label: "Minimum 8 characters",
      isValid: password.length >= 8,
    },
    {
      label: "Uppercase and lowercase letters",
      isValid: /[A-Z]/.test(password) && /[a-z]/.test(password),
    },
    {
      label: "Special character (!@#$%^&*)",
      isValid: /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password),
    },
  ]

  const visibleRules = onlyShowInvalid ? rules.filter((rule) => !rule.isValid) : rules

  if (visibleRules.length === 0) {
    return null
  }

  return (
    <div className="mt-2 space-y-2">
      {visibleRules.map((rule) => (
        <div key={rule.label} className="flex items-center gap-2">
          <span
            className={`flex-shrink-0 font-bold text-sm w-4 h-4 flex items-center justify-center ${
              rule.isValid
                ? "text-green-600"
                : "text-red-400"
            }`}
          >
            {rule.isValid ? "✓" : "✗"}
          </span>
          <span
            className={`text-xs ${
              rule.isValid
                ? "text-green-600"
                : "text-muted-foreground"
            }`}
          >
            {rule.label}
          </span>
        </div>
      ))}
    </div>
  )
}
