# RankStein Frontend

Next.js operator interface for RankStein.

The frontend is for monitoring and operating the SEO platform. Subscriber administration is deliberately not implemented here; use the root CLI commands under `python rankstein.py subscribers ...` so subscription changes stay scriptable, auditable, and separate from the public UI surface.

## Stack

- Next.js 16+
- React 19+
- Tailwind CSS 4
- TypeScript

## Development

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## Backend Assumptions

- API development server runs at `http://localhost:8080` unless configured otherwise.
- Public subscriber capture may call backend routes, but admin operations remain CLI-only.
- Do not expose Supabase service role keys, Gemini credentials, Pinterest credentials, or browser session paths to client components.

## Verification

```bash
npm run lint
npm run build
```

Run the root Python validation after frontend changes that affect automation status displays:

```bash
cd ..
python scripts/dev/validate_automation.py
```
