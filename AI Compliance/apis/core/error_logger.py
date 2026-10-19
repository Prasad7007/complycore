"""
Comprehensive error logging utility for the compliance AI application.
Provides structured error logging with context information for debugging and monitoring.
"""

import logging
import json
import traceback
import sys
from typing import Any, Dict, Optional, List
from datetime import datetime
from enum import Enum

# Configure logger
logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels"""
    CRITICAL = "CRITICAL"  # System breaking errors
    ERROR = "ERROR"        # Major operation failures
    WARNING = "WARNING"    # Recoverable issues
    INFO = "INFO"          # Important events


class ErrorCategory(Enum):
    """Error categories for better organization"""
    DATABASE = "DATABASE"
    AI_SERVICE = "AI_SERVICE"
    FILE_UPLOAD = "FILE_UPLOAD"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    VALIDATION = "VALIDATION"
    EXTERNAL_API = "EXTERNAL_API"
    S3_STORAGE = "S3_STORAGE"
    DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
    BEDROCK_AI = "BEDROCK_AI"
    WORKFLOW = "WORKFLOW"
    AUDIT = "AUDIT"
    GENERAL = "GENERAL"


class ErrorLogger:
    """
    Centralized error logging utility with structured logging capabilities.
    Logs errors with context, severity, category, and stack traces for comprehensive error tracking.
    """

    @staticmethod
    def log_error(
        error: Exception,
        category: ErrorCategory,
        operation: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        include_traceback: bool = True,
    ) -> Dict[str, Any]:
        """
        Log error with full context and structured information.
        
        Args:
            error: The exception object
            category: Error category (DATABASE, AI_SERVICE, etc.)
            operation: Description of the operation that failed
            severity: Error severity level
            context: Additional context information
            user_id: ID of user performing the operation
            resource_id: ID of the resource being accessed
            include_traceback: Whether to include full traceback
        
        Returns:
            Dictionary containing logged error details
        """
        error_dict = {
            "timestamp": datetime.utcnow().isoformat(),
            "category": category.value,
            "operation": operation,
            "severity": severity.value,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }

        # Add optional context
        if user_id:
            error_dict["user_id"] = user_id
        if resource_id:
            error_dict["resource_id"] = resource_id
        if context:
            error_dict["context"] = context

        # Include traceback for debugging
        if include_traceback:
            error_dict["traceback"] = traceback.format_exc()

        # Console output with proper formatting
        log_level = getattr(logging, severity.value)
        logger_func = getattr(logger, severity.value.lower())

        # Format message for console
        console_message = (
            f"[{category.value}] {operation} - {type(error).__name__}: {str(error)}"
        )
        if user_id:
            console_message += f" | User: {user_id}"
        if resource_id:
            console_message += f" | Resource: {resource_id}"

        # Log to console with traceback
        if include_traceback:
            logger_func(console_message, exc_info=True)
        else:
            logger_func(console_message)

        # Also print to stdout for visibility
        print(
            f"\n{'='*80}",
            file=sys.stderr,
        )
        print(
            f"[{severity.value}] [{category.value}] {datetime.utcnow().isoformat()}",
            file=sys.stderr,
        )
        print(f"Operation: {operation}", file=sys.stderr)
        print(f"Error: {type(error).__name__}: {str(error)}", file=sys.stderr)
        if user_id:
            print(f"User ID: {user_id}", file=sys.stderr)
        if resource_id:
            print(f"Resource ID: {resource_id}", file=sys.stderr)
        if context:
            print(f"Context: {json.dumps(context, indent=2, default=str)}", file=sys.stderr)
        if include_traceback:
            print(f"\nTraceback:\n{traceback.format_exc()}", file=sys.stderr)
        print(f"{'='*80}\n", file=sys.stderr)

        # Trigger email alerts for ERROR and CRITICAL severity issues
        if severity in (ErrorSeverity.ERROR, ErrorSeverity.CRITICAL):
            try:
                import boto3
                import os
                import html

                sender = os.getenv("SES_SOURCE_EMAIL", "no-reply@complycore.ca")
                aws_region = os.getenv("AWS_REGION", "us-east-1")
                recipients = ["shreyansh@elevatetrust.ai", "prasad.a@elevatetrust.ai"]

                subject = f"[ERROR ALERT] [{category.value}] {operation} - {type(error).__name__}"

                context_str = json.dumps(context or {}, indent=2, default=str)
                tb_str = traceback.format_exc() if include_traceback else "Traceback not included"

                body_text = (
                    f"An error has occurred in the Compliance AI application.\n\n"
                    f"Timestamp: {datetime.utcnow().isoformat()}\n"
                    f"Category: {category.value}\n"
                    f"Severity: {severity.value}\n"
                    f"Operation: {operation}\n"
                    f"User ID: {user_id or 'N/A'}\n"
                    f"Resource ID: {resource_id or 'N/A'}\n\n"
                    f"Error Type: {type(error).__name__}\n"
                    f"Error Message: {str(error)}\n\n"
                    f"Context:\n{context_str}\n\n"
                    f"Traceback:\n{tb_str}"
                )

                body_html = f"""<html>
                <body style="font-family: monospace; font-size: 13px; color: #1e293b; background-color: #f8fafc; padding: 20px;">
                    <div style="max-width: 800px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                        <h2 style="color: #dc2626; border-bottom: 2px solid #fee2e2; padding-bottom: 12px; margin-top: 0;">Error Alert Triggered</h2>
                        <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                            <tr><td style="padding: 6px 0; font-weight: bold; width: 150px;">Timestamp:</td><td>{datetime.utcnow().isoformat()}</td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">Category:</td><td><span style="background-color: #f1f5f9; padding: 2px 6px; border-radius: 4px;">{category.value}</span></td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">Severity:</td><td><span style="background-color: #fef2f2; color: #991b1b; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{severity.value}</span></td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">Operation:</td><td>{operation}</td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">User ID:</td><td>{user_id or 'N/A'}</td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">Resource ID:</td><td>{resource_id or 'N/A'}</td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">Error Type:</td><td><strong>{type(error).__name__}</strong></td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">Message:</td><td style="color: #475569;">{html.escape(str(error))}</td></tr>
                        </table>
                        
                        <h3 style="color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px;">Context</h3>
                        <pre style="background-color: #f1f5f9; padding: 12px; border-radius: 6px; overflow-x: auto;">{html.escape(context_str)}</pre>
                        
                        <h3 style="color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px;">Traceback</h3>
                        <pre style="background-color: #f1f5f9; padding: 12px; border-radius: 6px; overflow-x: auto; color: #b91c1c;">{html.escape(tb_str)}</pre>
                    </div>
                </body>
                </html>"""

                client = boto3.client("ses", region_name=aws_region)
                client.send_email(
                    Source=sender,
                    Destination={"ToAddresses": recipients},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": body_text, "Charset": "UTF-8"},
                            "Html": {"Data": body_html, "Charset": "UTF-8"},
                        },
                    },
                )
                print(f"Error Alert Email sent to {recipients}", file=sys.stdout)
            except Exception as email_err:
                print(f"Failed to send error alert email: {email_err}", file=sys.stderr)

        return error_dict


    @staticmethod
    def log_database_error(
        error: Exception,
        operation: str,
        query: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log database-specific errors"""
        db_context = {"query": query} if query else {}
        if context:
            db_context.update(context)

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.DATABASE,
            operation=operation,
            severity=ErrorSeverity.CRITICAL if "connection" in str(error).lower() else ErrorSeverity.ERROR,
            context=db_context,
            user_id=user_id,
        )

    @staticmethod
    def log_ai_service_error(
        error: Exception,
        operation: str,
        service: str = "Bedrock",
        context: Optional[Dict[str, Any]] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log AI service-specific errors (Bedrock, Claude, etc.)"""
        ai_context = {"service": service}
        if document_id:
            ai_context["document_id"] = document_id
        if context:
            ai_context.update(context)

        # Bedrock errors are often critical
        category = ErrorCategory.BEDROCK_AI if service == "Bedrock" else ErrorCategory.AI_SERVICE
        severity = ErrorSeverity.CRITICAL if "quota" in str(error).lower() or "throttling" in str(error).lower() else ErrorSeverity.ERROR

        return ErrorLogger.log_error(
            error=error,
            category=category,
            operation=operation,
            severity=severity,
            context=ai_context,
            user_id=user_id,
        )

    @staticmethod
    def log_file_upload_error(
        error: Exception,
        operation: str,
        filename: Optional[str] = None,
        file_size: Optional[int] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log file upload-specific errors"""
        upload_context = {}
        if filename:
            upload_context["filename"] = filename
        if file_size:
            upload_context["file_size"] = file_size
        if context:
            upload_context.update(context)

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.FILE_UPLOAD,
            operation=operation,
            severity=ErrorSeverity.ERROR,
            context=upload_context,
            user_id=user_id,
        )

    @staticmethod
    def log_s3_error(
        error: Exception,
        operation: str,
        bucket: Optional[str] = None,
        key: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log S3 storage-specific errors"""
        s3_context = {}
        if bucket:
            s3_context["bucket"] = bucket
        if key:
            s3_context["key"] = key
        if context:
            s3_context.update(context)

        # S3 connection errors are critical
        severity = ErrorSeverity.CRITICAL if "connection" in str(error).lower() else ErrorSeverity.ERROR

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.S3_STORAGE,
            operation=operation,
            severity=severity,
            context=s3_context,
        )

    @staticmethod
    def log_document_processing_error(
        error: Exception,
        operation: str,
        document_id: Optional[str] = None,
        document_name: Optional[str] = None,
        processing_stage: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log document processing errors (parsing, chunking, etc.)"""
        doc_context = {}
        if document_id:
            doc_context["document_id"] = document_id
        if document_name:
            doc_context["document_name"] = document_name
        if processing_stage:
            doc_context["processing_stage"] = processing_stage
        if context:
            doc_context.update(context)

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.DOCUMENT_PROCESSING,
            operation=operation,
            severity=ErrorSeverity.ERROR,
            context=doc_context,
            user_id=user_id,
        )

    @staticmethod
    def log_validation_error(
        error: Exception,
        operation: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log validation errors"""
        val_context = {}
        if field:
            val_context["field"] = field
        if value is not None:
            val_context["value"] = str(value)
        if context:
            val_context.update(context)

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.VALIDATION,
            operation=operation,
            severity=ErrorSeverity.WARNING,
            context=val_context,
            include_traceback=False,
        )

    @staticmethod
    def log_authentication_error(
        error: Exception,
        operation: str,
        username: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log authentication errors"""
        auth_context = {}
        if username:
            auth_context["username"] = username
        if context:
            auth_context.update(context)

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.AUTHENTICATION,
            operation=operation,
            severity=ErrorSeverity.WARNING,
            context=auth_context,
            include_traceback=False,
        )

    @staticmethod
    def log_workflow_error(
        error: Exception,
        operation: str,
        workflow_id: Optional[str] = None,
        review_id: Optional[str] = None,
        current_stage: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log workflow-specific errors"""
        workflow_context = {}
        if workflow_id:
            workflow_context["workflow_id"] = workflow_id
        if review_id:
            workflow_context["review_id"] = review_id
        if current_stage:
            workflow_context["current_stage"] = current_stage
        if context:
            workflow_context.update(context)

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.WORKFLOW,
            operation=operation,
            severity=ErrorSeverity.ERROR,
            context=workflow_context,
            user_id=user_id,
        )

    @staticmethod
    def log_external_api_error(
        error: Exception,
        operation: str,
        api_endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Log external API errors"""
        api_context = {}
        if api_endpoint:
            api_context["api_endpoint"] = api_endpoint
        if status_code:
            api_context["status_code"] = status_code
        if context:
            api_context.update(context)

        severity = ErrorSeverity.CRITICAL if status_code and status_code >= 500 else ErrorSeverity.ERROR

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.EXTERNAL_API,
            operation=operation,
            severity=severity,
            context=api_context,
        )

    @staticmethod
    def log_permission_error(
        error: Exception | str,
        operation: str,
        resource: Optional[str] = None,
        requiredRole: Optional[str] = None,
        userId: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Log authorization/permission errors.
        
        Args:
            error: The exception or error message
            operation: The operation that was being performed
            resource: The resource being accessed
            requiredRole: The required role for access
            userId: ID of the user attempting the action
            context: Additional context information
        """
        full_context = {
            "operation": operation,
            "resource": resource,
            "required_role": requiredRole,
            "user_id": userId,
            **(context or {}),
        }

        return ErrorLogger.log_error(
            error=error,
            category=ErrorCategory.AUTHORIZATION,
            operation=operation,
            severity=ErrorSeverity.WARNING,
            context=full_context,
        )

    @staticmethod
    def log_info(message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Log informational message"""
        info_dict = {
            "timestamp": datetime.utcnow().isoformat(),
            "severity": ErrorSeverity.INFO.value,
            "message": message,
        }
        if context:
            info_dict["context"] = context

        logger.info(message)
        print(f"[INFO] {datetime.utcnow().isoformat()} - {message}", file=sys.stdout)
        if context:
            print(f"  Context: {json.dumps(context, indent=2, default=str)}", file=sys.stdout)

        return info_dict


# Create convenient aliases
log_error = ErrorLogger.log_error
log_db_error = ErrorLogger.log_database_error
log_ai_error = ErrorLogger.log_ai_service_error
log_upload_error = ErrorLogger.log_file_upload_error
log_s3_error = ErrorLogger.log_s3_error
log_doc_error = ErrorLogger.log_document_processing_error
log_validation_error = ErrorLogger.log_validation_error
log_auth_error = ErrorLogger.log_authentication_error
log_permission_error = ErrorLogger.log_permission_error
log_workflow_error = ErrorLogger.log_workflow_error
log_api_error = ErrorLogger.log_external_api_error
log_info = ErrorLogger.log_info
