<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->
# RankStein Frontend Agent Notes - 2026-05-13

- Keep subscriber administration out of the frontend; use `python rankstein.py subscribers ...`.
- Never expose Supabase service role keys, Gemini CLI auth state, Pinterest credentials, or browser session paths in client code.
- If frontend work displays automation state, keep labels compatible with the validated Firefox/Chromium and multi-account Pinterest model.
- If frontend work displays model or image settings, show `auto`/Gemini 3/3.1 CLI subscription mode and the NanoBanana image contract. Do not direct operators toward Google/Gemini API-key orchestration.
- Image-generation UX must preserve domain handle, destination URL, and Pinterest account handle as metadata; do not render URLs or long recipe text into generated images.
- Run `npm run lint` or `npm run build` for frontend changes when dependencies are available.

---
