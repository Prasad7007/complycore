/**
 * Comprehensive error logging utility for the frontend application.
 * Provides structured error logging with context information for debugging and monitoring.
 */

export const ErrorSeverity = {
  CRITICAL: "CRITICAL",
  ERROR: "ERROR",
  WARNING: "WARNING",
  INFO: "INFO",
} as const

export type ErrorSeverityType = (typeof ErrorSeverity)[keyof typeof ErrorSeverity]

export const ErrorCategory = {
  API_REQUEST: "API_REQUEST",
  FILE_UPLOAD: "FILE_UPLOAD",
  AUTHENTICATION: "AUTHENTICATION",
  FORM_VALIDATION: "FORM_VALIDATION",
  USER_ACTION: "USER_ACTION",
  COMPONENT_ERROR: "COMPONENT_ERROR",
  DOCUMENT_PROCESSING: "DOCUMENT_PROCESSING",
  AI_ANALYSIS: "AI_ANALYSIS",
  NETWORK: "NETWORK",
  BROWSER_API: "BROWSER_API",
  STATE_MANAGEMENT: "STATE_MANAGEMENT",
  PERMISSION: "PERMISSION",
  GENERAL: "GENERAL",
} as const

export type ErrorCategoryType = (typeof ErrorCategory)[keyof typeof ErrorCategory]

export interface ErrorLogEntry {
  timestamp: string
  category: string
  operation: string
  severity: string
  error_type: string
  error_message: string
  stackTrace?: string
  context?: Record<string, any>
  userId?: string
  resourceId?: string
  userAgent?: string
  url?: string
}

export class FrontendErrorLogger {
  /**
   * Log error with full context and structured information.
   * Logs to console and optionally to a remote service.
   */
  static logError(
    error: Error | string,
    category: ErrorCategoryType,
    operation: string,
    severity: ErrorSeverityType = ErrorSeverity.ERROR,
    context?: Record<string, any>,
    userId?: string,
    resourceId?: string,
  ): ErrorLogEntry {
    const errorMessage = error instanceof Error ? error.message : String(error)
    const stackTrace = error instanceof Error ? error.stack : undefined
    const timestamp = new Date().toISOString()

    const logEntry: ErrorLogEntry = {
      timestamp,
      category: category,
      operation,
      severity: severity,
      error_type: error instanceof Error ? error.constructor.name : "Unknown",
      error_message: errorMessage,
      stackTrace,
      context,
      userId,
      resourceId,
      userAgent: navigator.userAgent,
      url: window.location.href,
    }

    // Format for console
    const consoleStyle = `
      color: white;
      background-color: ${FrontendErrorLogger.getSeverityColor(severity)};
      padding: 8px 12px;
      border-radius: 4px;
      font-weight: bold;
    `

    const consoleMessage = `[${severity}] [${category}] ${operation}`
    console.error(
      `%c${consoleMessage}`,
      consoleStyle,
      {
        operation,
        error: errorMessage,
        severity,
        category,
        userId,
        resourceId,
        context,
        timestamp,
      },
    )

    // Log full details
    console.error("📋 Error Details:", logEntry)

    // Log stack trace if available
    if (stackTrace) {
      console.error("📚 Stack Trace:")
      console.error(stackTrace)
    }

    // Log context if available
    if (context) {
      console.error("🔧 Context:", context)
    }

    // You can add logic here to send to a remote logging service
    // this.sendToRemoteService(logEntry);

    return logEntry
  }

  /**
   * Log API request errors with detailed information
   */
  static logApiError(
    error: Error | string,
    endpoint: string,
    method?: string,
    statusCode?: number,
    context?: Record<string, any>,
    userId?: string,
  ): ErrorLogEntry {
    const severity: ErrorSeverityType =
      statusCode && statusCode >= 500 ? ErrorSeverity.CRITICAL : ErrorSeverity.ERROR

    const apiContext = {
      endpoint,
      method: method || "UNKNOWN",
      statusCode,
      ...context,
    }

    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.API_REQUEST,
      `API Request Failed: ${method} ${endpoint}`,
      severity,
      apiContext,
      userId,
    )
  }

  /**
   * Log file upload errors
   */
  static logUploadError(
    error: Error | string,
    operation: string,
    fileName?: string,
    fileSize?: number,
    fileType?: string,
    context?: Record<string, any>,
    userId?: string,
  ): ErrorLogEntry {
    const uploadContext = {
      fileName,
      fileSize,
      fileType,
      ...context,
    }

    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.FILE_UPLOAD,
      `Upload Failed: ${operation}`,
      ErrorSeverity.ERROR as ErrorSeverityType,
      uploadContext,
      userId,
    )
  }

  /**
   * Log form validation errors
   */
  static logValidationError(
    error: Error | string,
    field?: string,
    value?: any,
    context?: Record<string, any>,
  ): ErrorLogEntry {
    const validationContext = {
      field,
      value: value != null ? String(value) : null,
      ...context,
    }

    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.FORM_VALIDATION,
      `Validation Error${field ? ` in ${field}` : ""}`,
      ErrorSeverity.WARNING as ErrorSeverityType,
      validationContext,
    )
  }

  /**
   * Log authentication errors
   */
  static logAuthError(
    error: Error | string,
    operation: string,
    username?: string,
    context?: Record<string, any>,
  ): ErrorLogEntry {
    const authContext = {
      username,
      ...context,
    }

    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.AUTHENTICATION,
      operation,
      ErrorSeverity.WARNING as ErrorSeverityType,
      authContext,
    )
  }

  /**
   * Log component errors (React error boundaries)
   */
  static logComponentError(
    error: Error,
    componentName: string,
    context?: Record<string, any>,
    userId?: string,
  ): ErrorLogEntry {
    const componentContext = {
      component: componentName,
      ...context,
    }

    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.COMPONENT_ERROR,
      `Component Error in ${componentName}`,
      ErrorSeverity.CRITICAL as ErrorSeverityType,
      componentContext,
      userId,
    )
  }

  /**
   * Log document processing errors
   */
  static logDocumentError(
    error: Error | string,
    operation: string,
    documentId?: string,
    documentName?: string,
    processingStage?: string,
    context?: Record<string, any>,
    userId?: string,
  ): ErrorLogEntry {
    const docContext = {
      documentId,
      documentName,
      processingStage,
      ...context,
    }

    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.DOCUMENT_PROCESSING,
      operation,
      ErrorSeverity.ERROR as ErrorSeverityType,
      docContext,
      userId,
    )
  }

  /**
   * Log AI analysis errors
   */
  static logAiAnalysisError(
    error: Error | string,
    operation: string,
    documentId?: string,
    reviewId?: string,
    context?: Record<string, any>,
    userId?: string,
  ): ErrorLogEntry {
    const aiContext = {
      documentId,
      reviewId,
      ...context,
    }

    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.AI_ANALYSIS,
      operation,
      ErrorSeverity.ERROR as ErrorSeverityType,
      aiContext,
      userId,
    )
  }

  /**
   * Log network errors
   */
  static logNetworkError(
    error: Error | string,
    context?: Record<string, any>,
  ): ErrorLogEntry {
    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.NETWORK,
      "Network Error",
      ErrorSeverity.CRITICAL as ErrorSeverityType,
      context,
    )
  }

  /**
   * Log permission/authorization errors
   */
  static logPermissionError(
    error: Error | string,
    operation: string,
    resource?: string,
    requiredRole?: string,
    userId?: string,
  ): ErrorLogEntry {
    const permContext = {
      resource,
      requiredRole,
    }

    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.PERMISSION,
      operation,
      ErrorSeverity.WARNING as ErrorSeverityType,
      permContext,
      userId,
    )
  }

  /**
   * Log user action errors
   */
  static logUserActionError(
    error: Error | string,
    action: string,
    context?: Record<string, any>,
    userId?: string,
  ): ErrorLogEntry {
    return FrontendErrorLogger.logError(
      error,
      ErrorCategory.USER_ACTION,
      action,
      ErrorSeverity.ERROR as ErrorSeverityType,
      context,
      userId,
    )
  }

  /**
   * Log informational message
   */
  static logInfo(message: string, context?: Record<string, any>, userId?: string): ErrorLogEntry {
    const timestamp = new Date().toISOString()
    const logEntry: ErrorLogEntry = {
      timestamp,
      category: ErrorCategory.GENERAL,
      operation: message,
      severity: ErrorSeverity.INFO,
      error_type: "Info",
      error_message: message,
      context,
      userId,
      userAgent: navigator.userAgent,
      url: window.location.href,
    }

    console.log(
      `%c[INFO] ${message}`,
      "color: #4CAF50; font-weight: bold; font-size: 12px;",
      context || "",
    )

    return logEntry
  }

  /**
   * Log warning message
   */
  static logWarning(message: string, context?: Record<string, any>): ErrorLogEntry {
    const timestamp = new Date().toISOString()
    const logEntry: ErrorLogEntry = {
      timestamp,
      category: ErrorCategory.GENERAL,
      operation: message,
      severity: ErrorSeverity.WARNING,
      error_type: "Warning",
      error_message: message,
      context,
      userAgent: navigator.userAgent,
      url: window.location.href,
    }

    console.warn(
      `%c[WARNING] ${message}`,
      "color: #FFA500; font-weight: bold; font-size: 12px;",
      context || "",
    )

    return logEntry
  }

  /**
   * Get color for severity level
   */
  private static getSeverityColor(severity: ErrorSeverityType): string {
    switch (severity) {
      case "CRITICAL":
        return "#D32F2F" // Red
      case "ERROR":
        return "#F57C00" // Orange
      case "WARNING":
        return "#FFA000" // Amber
      case "INFO":
        return "#1976D2" // Blue
      default:
        return "#757575"
    }
  }

  /**
   * Setup global error handler for unhandled errors
   */
  static setupGlobalErrorHandler(): void {
    // Handle unhandled promise rejections
    window.addEventListener("unhandledrejection", (event) => {
      FrontendErrorLogger.logError(
        event.reason instanceof Error
          ? event.reason
          : new Error(String(event.reason)),
        ErrorCategory.GENERAL,
        "Unhandled Promise Rejection",
        ErrorSeverity.CRITICAL,
      )
    })

    // Handle global errors
    window.addEventListener("error", (event) => {
      FrontendErrorLogger.logError(
        event.error instanceof Error
          ? event.error
          : new Error(event.message || "Unknown Error"),
        ErrorCategory.GENERAL,
        "Global Error Handler",
        ErrorSeverity.CRITICAL,
        {
          filename: event.filename,
          lineno: event.lineno,
          colno: event.colno,
        },
      )
    })
  }
}

// Create convenient aliases
export const logFrontendError = FrontendErrorLogger.logError
export const logApiError = FrontendErrorLogger.logApiError
export const logUploadError = FrontendErrorLogger.logUploadError
export const logValidationError = FrontendErrorLogger.logValidationError
export const logAuthError = FrontendErrorLogger.logAuthError
export const logComponentError = FrontendErrorLogger.logComponentError
export const logDocumentError = FrontendErrorLogger.logDocumentError
export const logAiAnalysisError = FrontendErrorLogger.logAiAnalysisError
export const logNetworkError = FrontendErrorLogger.logNetworkError
export const logPermissionError = FrontendErrorLogger.logPermissionError
export const logUserActionError = FrontendErrorLogger.logUserActionError
export const logFrontendInfo = FrontendErrorLogger.logInfo
export const logFrontendWarning = FrontendErrorLogger.logWarning
