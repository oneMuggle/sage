/**
 * Context menu dictionary (English). Key set is derived from the zh dictionary
 * so the two locales cannot drift.
 */
import { zhContextMenu } from '../zh/contextMenu';

export const enContextMenu: Record<keyof typeof zhContextMenu, string> = {
  'contextMenu.common.open': 'Open',
  'contextMenu.common.copy': 'Copy',
  'contextMenu.common.copyPath': 'Copy Path',
  'contextMenu.common.copyName': 'Copy File Name',
  'contextMenu.common.revealInFolder': 'Show in Folder',
  'contextMenu.common.remove': 'Remove',
  'contextMenu.common.rename': 'Rename',
  'contextMenu.common.delete': 'Delete…',
  'contextMenu.common.copied': 'Copied',
  'contextMenu.common.copyFailed': 'Copy failed',
  'contextMenu.common.selectionCopy': 'Copy Selection',
  'contextMenu.common.selectionQuote': 'Quote Selection',
  'contextMenu.common.inspect': 'Inspect Element',
  'contextMenu.common.actionFailed': 'Action failed: {message}',

  'contextMenu.session.open': 'Open Session',
  'contextMenu.session.pin': 'Pin Session',
  'contextMenu.session.unpin': 'Unpin Session',
  'contextMenu.session.archive': 'Archive Session',
  'contextMenu.session.unarchive': 'Unarchive Session',
  'contextMenu.session.copyTitle': 'Copy Title',
  'contextMenu.session.exportMarkdown': 'Export Markdown',
  'contextMenu.session.exportHtml': 'Export HTML',
  'contextMenu.session.viewForkTree': 'View Fork Tree',
  'contextMenu.session.delete': 'Delete Session…',
  'contextMenu.session.deleteTitle': 'Delete Session',
  'contextMenu.session.deleteMessage':
    'This permanently deletes the session "{title}" and all of its messages. This cannot be undone.',

  'contextMenu.message.quote': 'Quote to Composer',
  'contextMenu.message.copyMarkdown': 'Copy as Markdown',
  'contextMenu.message.editResend': 'Edit & Resend',
  'contextMenu.message.regenerate': 'Regenerate',
  'contextMenu.message.feedbackUp': 'Helpful',
  'contextMenu.message.feedbackDown': 'Not Helpful',
  'contextMenu.message.fork': 'Fork from Here',
  'contextMenu.message.rewind': 'Rewind to Here',
  'contextMenu.message.saveToMemory': 'Save to Memory',
  'contextMenu.message.delete': 'Delete Message…',
  'contextMenu.message.deleteTitle': 'Delete Message',
  'contextMenu.message.deleteBody': 'This permanently deletes the message. This cannot be undone.',

  'contextMenu.codeBlock.copy': 'Copy Code',
  'contextMenu.codeBlock.copyFence': 'Copy as Markdown Fence',
  'contextMenu.table.copy': 'Copy Table (TSV)',
  'contextMenu.image.view': 'View Image',

  'contextMenu.wiki.newFile': 'New File',
  'contextMenu.wiki.nameLabel': 'Name',
  'contextMenu.wiki.deleteTitle': 'Delete Wiki Entry',
  'contextMenu.wiki.deleteMessage':
    'This deletes "{path}"; deleting a folder recursively removes all files inside. This cannot be undone.',
  'contextMenu.wiki.nameRequired': 'Name cannot be empty',
  'contextMenu.wiki.nameInvalid': 'Name cannot contain / or ..',
  'contextMenu.wiki.createFailed': 'Create failed: {message}',
  'contextMenu.wiki.renameFailed': 'Rename failed: {message}',
  'contextMenu.wiki.deleteFailed': 'Delete failed: {message}',

  'contextMenu.change.expand': 'Expand Diff',
  'contextMenu.change.collapse': 'Collapse Diff',
  'contextMenu.change.accept': 'Accept Change',
  'contextMenu.change.revert': 'Revert Change…',
  'contextMenu.change.toggleView': 'Toggle Diff View',
  'contextMenu.change.openInEditor': 'Open in Editor',
  'contextMenu.change.openInPanel': 'Open in Panel',

  'contextMenu.artifact.open': 'Open Artifact',
  'contextMenu.artifact.reveal': 'Show in File Manager',
  'contextMenu.artifact.openDelivery': 'Open Delivery Workspace',
};
