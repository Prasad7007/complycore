import boto3
import json
import logging
from botocore.exceptions import ClientError
from apis.services.ai.core import config
from botocore.config import Config

logger = logging.getLogger(__name__)

# Initialize the S3 client using credentials from config
s3_client = boto3.client(
    "s3",
    aws_access_key_id=config.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
    region_name=config.AWS_REGION,
    endpoint_url=config.S3_ENDPOINT_URL,
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"} if config.S3_ENDPOINT_URL else {},
    ),
)

def _put_linkedin_post(base_prefix: str, json_data: dict, media_files: list[tuple[str, bytes]]) -> None:
    """Internal: save JSON and media under base_prefix (e.g. linkedin_posts/educational/{post_id})."""
    json_key = f"{base_prefix}/data.json"
    try:
        s3_client.put_object(
            Bucket=config.AWS_S3_BUCKET,
            Key=json_key,
            Body=json.dumps(json_data, indent=2),
            ContentType="application/json"
        )
        logger.info("Successfully saved LinkedIn JSON to s3://%s/%s", config.AWS_S3_BUCKET, json_key)
    except ClientError as e:
        logger.error("Failed to save LinkedIn JSON to S3: %s", e)
        raise

    for filename, file_bytes in media_files:
        media_key = f"{base_prefix}/{filename}"
        content_type = "application/octet-stream"
        if filename.lower().endswith(".pdf"):
            content_type = "application/pdf"
        elif filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            ext = filename.split(".")[-1].lower()
            ext = "jpeg" if ext == "jpg" else ext
            content_type = f"image/{ext}"
        elif filename.lower().endswith((".mp4", ".webm", ".mov")):
            ext = filename.split(".")[-1].lower()
            content_type = f"video/{ext}" if ext != "mov" else "video/quicktime"
        try:
            s3_client.put_object(
                Bucket=config.AWS_S3_BUCKET,
                Key=media_key,
                Body=file_bytes,
                ContentType=content_type
            )
            logger.info("Successfully saved media to s3://%s/%s", config.AWS_S3_BUCKET, media_key)
        except ClientError as e:
            logger.error("Failed to save media %s to S3: %s", filename, e)
            raise


def save_linkedin_post(post_id: str, json_data: dict, media_files: list[tuple[str, bytes]] | None = None) -> None:
    """
    Saves a LinkedIn post under linkedin_posts/{post_id}/ (JSON + media).
    """
    _put_linkedin_post(f"linkedin_posts/{post_id}", json_data, media_files or [])


def save_linkedin_post_educational(post_id: str, json_data: dict, media_files: list[tuple[str, bytes]] | None = None) -> None:
    """
    Saves a LinkedIn post under marketing folder structure: linkedin_posts/educational/{post_id}/.
    Bucket already has marketing_docs; this adds linkedin_posts/educational/ for each post (JSON + images/video/PDF).
    """
    _put_linkedin_post(f"linkedin_posts/educational/{post_id}", json_data, media_files or [])


def save_marketing_doc_versioned(document_id: str, file_name: str, file_bytes: bytes, content_type: str = "application/pdf") -> str:
    """
    Saves a marketing document (e.g., PDF) with versioning.
    Finds the highest existing version for the given document_id and increments it.
    Returns the new object key (S3 path).
    """
    # Base folder for this specific document
    prefix = f"marketing_docs/{document_id}/"
    
    # List existing versions to determine the next version number
    try:
        response = s3_client.list_objects_v2(Bucket=config.AWS_S3_BUCKET, Prefix=prefix)
    except ClientError as e:
        logger.error(f"Failed to list objects in S3: {e}")
        raise

    next_version = 1
    if 'Contents' in response:
        for obj in response['Contents']:
            key = obj['Key']
            # Expected format: marketing_docs/{document_id}/v{version}/{file_name}
            parts = key.split('/')
            if len(parts) >= 4 and parts[2].startswith('v'):
                try:
                    version_num = int(parts[2][1:])
                    if version_num >= next_version:
                        next_version = version_num + 1
                except ValueError:
                    pass

    # Construct the new key with the incremented version
    new_key = f"{prefix}v{next_version}/{file_name}"
    
    try:
        s3_client.put_object(
            Bucket=config.AWS_S3_BUCKET,
            Key=new_key,
            Body=file_bytes,
            ContentType=content_type
        )
        logger.info(f"Successfully saved versioned document to s3://{config.AWS_S3_BUCKET}/{new_key}")
        return new_key
    except ClientError as e:
        logger.error(f"Failed to save versioned document to S3: {e}")
        raise