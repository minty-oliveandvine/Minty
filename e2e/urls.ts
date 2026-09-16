// Where Flask lives. Own module so specs and the config can both import it (see
// onboarding/e2e/urls.ts for why not the config itself).
export const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5001';
