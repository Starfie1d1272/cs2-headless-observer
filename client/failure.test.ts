import { describe, expect, it } from 'vitest';
import { ViewerResearchError } from './viewer-research.js';
import { describeFailure } from './failure.js';
import { SourceBoundary } from './follow.js';

describe('research failure diagnostics', () => {
  it('keeps source, header, clock and I/O failures distinct without paths', () => {
    expect(describeFailure(new SourceBoundary('source-truncated'), 'read-source')).toMatchObject({
      category: 'source-boundary',
      reason: 'source-truncated',
      stage: 'read-source',
    });
    expect(describeFailure(new SourceBoundary('source-replaced'), 'read-source').reason).toBe(
      'source-replaced',
    );
    expect(describeFailure(new Error('invalid-cs2-demo-magic'), 'validate-header').reason).toBe(
      'invalid-cs2-demo-magic',
    );
    expect(
      describeFailure(new ViewerResearchError('tick-regressed', 6463, 6432), 'parse-demo'),
    ).toMatchObject({
      category: 'source-continuity',
      reason: 'tick-regressed',
      previousTick: 6463,
      currentTick: 6432,
    });
    const io = Object.assign(new Error('/private/credential-file'), { code: 'EACCES' });
    expect(describeFailure(io, 'open-source')).toEqual({
      category: 'io',
      reason: 'EACCES',
      stage: 'open-source',
    });
  });
  it('explicitly marks unknown parser text as omitted, rather than exporting payloads', () => {
    const diagnostic = describeFailure(new RangeError('secret-password-and-payload'), 'parse-demo');
    expect(diagnostic).toMatchObject({
      category: 'parser-or-runtime',
      errorType: 'RangeError',
      reason: 'unclassified-error',
    });
    expect(JSON.stringify(diagnostic)).not.toContain('secret-password');
  });
});
