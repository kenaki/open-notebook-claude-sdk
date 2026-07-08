import os

# ROOT DATA FOLDER
DATA_FOLDER = "./data"

# LANGGRAPH CHECKPOINT FILE
sqlite_folder = f"{DATA_FOLDER}/sqlite-db"
os.makedirs(sqlite_folder, exist_ok=True)
LANGGRAPH_CHECKPOINT_FILE = f"{sqlite_folder}/checkpoints.sqlite"

# UPLOADS FOLDER
UPLOADS_FOLDER = f"{DATA_FOLDER}/uploads"
os.makedirs(UPLOADS_FOLDER, exist_ok=True)

# MAX UPLOAD SIZE (MB). Uploads larger than this are rejected with HTTP 413
# before touching disk. 0 disables the limit (not recommended — the API host
# must then absorb arbitrarily large request bodies).
try:
    MAX_UPLOAD_SIZE_MB = int(os.environ.get("OPEN_NOTEBOOK_MAX_UPLOAD_MB", "500"))
except ValueError:
    MAX_UPLOAD_SIZE_MB = 500

# CHAT MEDIA FOLDER (image/video attachments on chat messages; files only, no DB
# record in v1 — see coordinator Q-mediastore)
CHAT_MEDIA_FOLDER = f"{UPLOADS_FOLDER}/chat-media"
os.makedirs(CHAT_MEDIA_FOLDER, exist_ok=True)

# TIKTOKEN CACHE FOLDER
# Reads TIKTOKEN_CACHE_DIR from the environment so Docker can redirect the cache
# to a path outside /data/ (which is typically volume-mounted and would hide the
# pre-baked encoding baked into the image at build time).
TIKTOKEN_CACHE_DIR = os.environ.get("TIKTOKEN_CACHE_DIR", "").strip() or f"{DATA_FOLDER}/tiktoken-cache"
os.makedirs(TIKTOKEN_CACHE_DIR, exist_ok=True)
