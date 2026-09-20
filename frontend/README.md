# EduPath frontend

Next.js 16 (App Router) + React 19 + Tailwind v4 + shadcn/ui (base-nova) + Motion.
Design rules: `../docs/FRONTEND_DESIGN_SYSTEM.md`; contracts: `../docs/ARCHITECTURE_CONTRACTS.md` §21.

```bash
npm install
npm run dev            # http://localhost:3000 (API at NEXT_PUBLIC_API_BASE_URL, default http://localhost:8000)
npm run build && npm run start
npm run lint
npm run test:e2e       # Playwright + axe; needs a running API and `npm run start`
```

Demo mode (off by default): put `NEXT_PUBLIC_DEMO_MODE=true` in `.env.local`. It adds buttons that
fill the demo learner's intake, upload the demo resume and answer with a common misconception, all
through the real endpoints. `e2e/journey.spec.ts` needs demo mode and a fresh database.
