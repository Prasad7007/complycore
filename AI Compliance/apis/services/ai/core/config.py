import os

# Fix for macOS + gRPC DNS resolution issues (often causes 'Could not contact DNS servers')
os.environ.setdefault("GRPC_DNS_RESOLVER", "native")
# ── LLM Provider ──────────────────────────────────
# Set LLM_PROVIDER=vertexai to switch to GCP Vertex AI (Gemini 2.5 Flash)
# Set LLM_PROVIDER=bedrock  to use AWS Bedrock (default)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "bedrock")

# ── AWS / Bedrock ─────────────────────────────────
BEDROCK_MODEL_ID    = os.getenv("BEDROCK_MODEL_ID", "meta.llama3-70b-instruct-v1:0")
AWS_REGION          = os.getenv("AWS_REGION", "ca-central-1")
# If using Vertex AI, use Gemini for classification too.
# Note: gemini-1.5-flash is NOT available in northamerica-northeast1.
if LLM_PROVIDER == "vertexai":
    CLASSIFIER_MODEL_ID = os.getenv("CLASSIFIER_MODEL_ID", "gemini-3.5-flash")
else:
    CLASSIFIER_MODEL_ID = os.getenv("CLASSIFIER_MODEL_ID", "meta.llama3-8b-instruct-v1:0")
# Optional explicit override for classifier when provider is Vertex.
VERTEX_CLASSIFIER_MODEL_ID = os.getenv("VERTEX_CLASSIFIER_MODEL_ID", "gemini-3.5-flash")


# ── GCP / Vertex AI ───────────────────────────────
# VERTEX_CREDENTIALS_JSON: full GCP service account JSON as a string
# (paste the entire contents of your service-account .json file here)
VERTEX_PROJECT_ID       = os.getenv("VERTEX_PROJECT_ID", "")
VERTEX_LOCATION         = os.getenv("VERTEX_LOCATION", "northamerica-northeast1")
VERTEX_MODEL_ID         = os.getenv("VERTEX_MODEL_ID", "gemini-3.5-flash")
VERTEX_CREDENTIALS_JSON = os.getenv("VERTEX_CREDENTIALS_JSON", "")  # inline SA JSON string

# ── Chunking ───────────────────────────────────────
# Target ~600 words per chunk (1-2 paragraphs) for precise violation attribution.
# For longer future docs, increase CHUNK_TARGET_TOKENS via .env (e.g. 1200 for 5k-word docs).
CHUNK_TARGET_TOKENS = int(os.getenv("CHUNK_TARGET_TOKENS", 1000))
CHUNK_MIN_TOKENS    = int(os.getenv("CHUNK_MIN_TOKENS",    600))
CHUNK_MAX_TOKENS    = int(os.getenv("CHUNK_MAX_TOKENS",    1500))

# ── Pipeline ───────────────────────────────────────
MAX_CHUNKS     = int(os.getenv("MAX_CHUNKS", 0))  # 0 = all
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", 16384))
# Cap Gemini vision calls per document (charts / analyzed images only).
MAX_VISION_IMAGES = int(os.getenv("MAX_VISION_IMAGES", "5"))
# When HTML has <table> tags: extra budget for table-as-image heuristics (skipped but signaled).
MAX_VISION_TABLE_IMAGES = int(os.getenv("MAX_VISION_TABLE_IMAGES", "10"))
# When HTML has zero <table>: include up to this many largest on-disk images (by file size), recall-first.
MAX_VISION_NO_TABLE_LARGEST_K = int(os.getenv("MAX_VISION_NO_TABLE_LARGEST_K", "8"))
# Skip tiny assets (icons) when building largest-K pool; can set 0 to disable.
MIN_VISION_IMAGE_BYTES = int(os.getenv("MIN_VISION_IMAGE_BYTES", "2048"))


AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "comply-core-uat")

# ── LinkedIn / Apify ─────────────────────────────────
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")