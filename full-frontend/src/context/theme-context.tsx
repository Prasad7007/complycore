import * as React from "react"
import { useLocation } from "react-router-dom"

const STORAGE_KEY = "ai-compliance-theme"

const LOGIN_FLOW_PATHS = [
  "/",
  "/login",
  "/loginotp",
  "/forgot-password",
  "/register",
  "/registerotp",
  "/pending-access",
]

type Theme = "light" | "dark"

type ThemeContextValue = {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null)

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light"
  const stored = localStorage.getItem(STORAGE_KEY) as Theme | null
  if (stored === "dark" || stored === "light") return stored
  if (window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark"
  return "light"
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<Theme>(getInitialTheme)
  const { pathname } = useLocation()
  const isLoginFlow = LOGIN_FLOW_PATHS.includes(pathname)
  const effectiveTheme: Theme = isLoginFlow ? "light" : theme

  React.useEffect(() => {
    const root = document.documentElement
    root.classList.remove("light", "dark")
    root.classList.add(effectiveTheme)
    if (!isLoginFlow) {
      localStorage.setItem(STORAGE_KEY, theme)
    }
  }, [effectiveTheme, theme, isLoginFlow])

  const setTheme = React.useCallback((next: Theme) => {
    setThemeState(next)
  }, [])

  const toggleTheme = React.useCallback(() => {
    setThemeState((prev) => (prev === "light" ? "dark" : "light"))
  }, [])

  const value = React.useMemo(
    () => ({ theme, setTheme, toggleTheme }),
    [theme, setTheme, toggleTheme]
  )

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const ctx = React.useContext(ThemeContext)
  if (!ctx) {
    throw new Error("useTheme must be used within ThemeProvider")
  }
  return ctx
}