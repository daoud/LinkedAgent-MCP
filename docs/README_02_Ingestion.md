# Phase 2: Content Ingestion Layer

## Dependencies
- Phase 1 complete (DB + models + config)

## Tasks

### T-2.1: Storage Client Abstraction
**Claude: Sonnet | Tokens: Medium**

Create `src/ingestion/storage_client.py`:
- Abstract base class `StorageClient` with methods: `upload(file_path) → storage_url`, `download(storage_url) → bytes`, `exists(storage_url) → bool`, `delete(storage_url)`
- `LocalStorageClient` — copies to `LOCAL_CONTENT_DIR`, returns local path
- `S3StorageClient` — uses `boto3`, uploads to `AWS_S3_BUCKET`, returns s3:// URL
- Factory function `get_storage_client(config) → StorageClient` based on `STORAGE_MODE`

Prompt strategy: Provide ABC + LocalStorageClient in one prompt. S3Client in second prompt.

### T-2.2: Content Extractor
**Claude: Sonnet | Tokens: Medium**

Create `src/ingestion/content_extractor.py`:
- `extract_content(file_path, mime_type) → str`
- Routes by MIME type:
  - `text/markdown`, `text/plain` → read as-is
  - `application/pdf` → `pymupdf` text extraction
  - `application/vnd.openxmlformats-officedocument.wordprocessingml.document` → `python-docx`
  - `image/*` → return empty string, store path in `image_refs`
- MIME detection via `python-magic` or file extension fallback
- Max input size check (reject files > 10MB)

Tests: One sample file per format in `test_content/`.

### T-2.3: Content Reader
**Claude: Sonnet | Tokens: Low**

Create `src/ingestion/content_reader.py`:
- `read_content(upload_id, db_session) → tuple[str, list[str]]` returns (text, image_refs)
- Queries `content_uploads` for storage_path and storage_type
- Uses `StorageClient` to download file
- Uses `ContentExtractor` to extract text
- Computes SHA256 `content_hash`, updates record
- Returns extracted text + image reference list

### T-2.4: Local Folder Watcher
**Claude: Sonnet | Tokens: Low**

Create `src/ingestion/local_watcher.py`:
- Watches `LOCAL_CONTENT_DIR` for new files using `watchdog`
- On new file: create `content_uploads` record with `storage_type=local`
- Calls FastAPI trigger endpoint (or direct pipeline invoke in dev)
- Ignores hidden files, temp files, duplicates (by filename)

Test: Drop a file in `test_content/`, confirm DB record created.

## Completion Criteria
- [ ] `LocalStorageClient` upload + download works
- [ ] PDF, DOCX, MD, TXT extraction works
- [ ] `read_content(upload_id)` returns text from any supported format
- [ ] Local watcher detects new files and creates DB records
- [ ] Content hash computed and stored

## Files Created
```
src/ingestion/__init__.py
src/ingestion/storage_client.py
src/ingestion/content_extractor.py
src/ingestion/content_reader.py
src/ingestion/local_watcher.py
tests/unit/test_content_extractor.py
tests/unit/test_storage_client.py
tests/integration/test_ingestion_flow.py
test_content/sample_post.md
test_content/sample_document.txt
```
