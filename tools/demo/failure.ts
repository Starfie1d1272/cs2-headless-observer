import { ViewerResearchError } from './viewer-research.ts';
import { SourceBoundary } from './follow.js';

const knownReasons = new Set([
  'source-replaced',
  'source-consumed-tail-rewritten',
  'source-truncated',
  'source-not-file',
  'source-byte-budget',
  'event-output-budget',
  'incomplete-demo-header',
  'invalid-cs2-demo-magic',
]);
const ioCodes = new Set([
  'ENOENT',
  'EACCES',
  'EPERM',
  'EIO',
  'ENOSPC',
  'EMFILE',
  'ENFILE',
  'EBADF',
]);

/** Preserve failure semantics while never copying arbitrary parser/path/payload text. */
export function describeFailure(error: unknown, stage: string) {
  if (error instanceof ViewerResearchError) {
    return {
      category: 'source-continuity',
      reason: error.code,
      stage,
      previousTick: error.previousTick,
      currentTick: error.currentTick,
    };
  }
  if (error instanceof Error && knownReasons.has(error.message)) {
    return {
      category: error instanceof SourceBoundary ? 'source-boundary' : 'input-or-budget',
      reason: error.message,
      stage,
    };
  }
  if (
    error instanceof Error &&
    'code' in error &&
    typeof error.code === 'string' &&
    ioCodes.has(error.code)
  ) {
    return { category: 'io', reason: error.code, stage };
  }
  const errorType =
    error instanceof RangeError ? 'RangeError' : error instanceof TypeError ? 'TypeError' : 'Error';
  return {
    category: 'parser-or-runtime',
    reason: 'unclassified-error',
    stage,
    errorType,
    messageOmitted: 'untrusted error text may contain source data',
  };
}
