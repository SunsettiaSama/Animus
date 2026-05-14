import { describe, it, expect } from 'vitest';
import { PATHS } from './index.js';

describe('PATHS (mirrored from static/js/api.js)', () => {
  it('infra.notify matches backend routers', () => {
    expect(PATHS.infra.notify.bark.config).toBe('/api/notify/bark/config');
    expect(PATHS.infra.notify.bark.test).toBe('/api/notify/bark/test');
    expect(PATHS.infra.notify.ntfy.config).toBe('/api/notify/ntfy/config');
    expect(PATHS.infra.notify.ntfy.test).toBe('/api/notify/ntfy/test');
  });
});
