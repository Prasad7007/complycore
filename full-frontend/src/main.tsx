import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "./App"
import { ThemeProvider } from "./context/theme-context"
import { FrontendErrorLogger } from "./lib/error-logger"
import "./index.css"

// Initialize global error handlers for unhandled errors and promise rejections
FrontendErrorLogger.setupGlobalErrorHandler()
console.log("[INIT] Global error handler initialized")

// Set user-timezone cookie so the backend always knows the viewer's local timezone.
// This cookie is automatically sent with every request (iframes, downloads, API calls).
try {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
  document.cookie = `user-timezone=${encodeURIComponent(tz)}; path=/; SameSite=Lax`
} catch {
  // If timezone detection fails, leave cookie unset — backend will default to UTC
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
)

console.log("[INIT] Frontend application initialized")