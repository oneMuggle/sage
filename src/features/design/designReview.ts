/**
 * Design review helpers — compose iterate feedback from lint issues.
 */
import type { ReviewResult } from '../../entities/design/types';

/** Build a user-visible iterate feedback block from the review issues. */
export function composeReviewFeedback(review: ReviewResult): string {
  if (review.issues.length === 0) return '';
  const lines = review.issues.map(
    (issue) => `- [${issue.severity === 'error' ? 'P0' : 'P1'}] ${issue.rule_id}: ${issue.message}`,
  );
  return `请修复以下设计质量问题：\n${lines.join('\n')}`;
}
