// P0/P1 (2026-11-04): attachment processing status dictionary.
// Split out because chatAndSider is close to the 800-line architecture ratchet.
export const enAttachmentStatus = {
  'chat.attachment_status.summary': 'Read {ok} file(s) · {chars} chars',
  'chat.attachment_status.ok': 'Read',
  'chat.attachment_status.skipped': 'Skipped',
  'chat.attachment_status.error': 'Failed',
  'chat.attachment_status.truncated': 'Content too long, truncated',
  'chat.attachment_status.rag': 'Injected by relevance',
  'chat.attachment_status.reason.not_document': 'Unrecognized file type, please re-upload',
  'chat.attachment_status.reason.not_utf8': 'File is not valid UTF-8 text',
  'chat.attachment_status.reason.empty_text': 'File is empty',
  'chat.attachment_status.reason.load_failed': 'Attachment missing or unreadable',
  'chat.attachment_status.reason.context_build_failed': 'Could not build context',
  'chat.attachment_status.reason.extract_failed': 'Document parsing failed',
  // P2 preflight rejection reasons
  'chat.attachment_status.reason.oversize': 'File exceeds 25MB limit',
  'chat.attachment_status.reason.unsupported': 'Unsupported file type',
  'chat.attachment_status.reason.count_exceeded': 'At most 10 attachments',
  'chat.attachment_status.reason.duplicate': 'A file with the same name already exists',
  'chat.attachment_upload_failed':
    'Pre-upload failed for these files; they will be retried on send: {files}',
} as const;
