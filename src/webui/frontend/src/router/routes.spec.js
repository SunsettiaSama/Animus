import { describe, it, expect } from 'vitest';
import { routes } from './routes.js';

describe('routes lazy loading', () => {
  it('every route uses dynamic import factory', () => {
    for (const r of routes) {
      expect(typeof r.component).toBe('function');
    }
  });
});
