# Stitch Atlas Academy — Optional Google sign-in and cross-device progress

**Current state:** implementation complete on a review branch; **NO Firebase project provisioned or connected**, no billing, no live Google users, no Supabase migrations, and no published patterns. The preview remains `noindex`.

## Why this can start free

- Firebase Authentication's standard Google provider is supported on the **Spark** no-cost plan (subject to limits).
- Cloud Firestore Standard has one free database per project, currently **1 GiB stored, 50,000 reads/day, 20,000 writes/day, 10 GiB monthly transfer**. Sources: https://firebase.google.com/pricing and https://firebase.google.com/docs/firestore/pricing.
- No Firebase service account or admin key is included. Public web config is not a server secret, though use Google Cloud API-key restrictions.
- Firestore stores only `academyProgress/{auth.uid}`: schema version, account reset generation, known lesson IDs, best score, completion timestamps, and server update time. Email and Google OAuth tokens are not stored inside progress documents.
- **The course and quizzes always work anonymously** when this integration is disconnected.

## Activation checklist (requires owner access to a Firebase account)

1. Create a **new, separate Firebase project on Spark**, with no billing linked. Choose a region appropriate for visitors; select the free **Standard Firestore** database. Do not connect either recipe database.
2. Enable **Google** at Firebase Authentication → Sign-in method and supply the Firebase project support email.
3. Deploy the reviewed `apps/stitch-atlas/firestore.rules` into that project's Firestore settings. **Test those rules first with the Firestore Emulator and at least two real separate user identities.** Cross-user reads, writes, collection queries and unexpected documents must be denied.
4. Firebase Authentication → Settings → Authorized domains: whitelist the **exact preview hostname** that people will use. Later add the real canonical domain. GitHub preview URLs may change; use a stable Vercel alias where practical.
5. Register a Firebase Web App, and add these **four public** values as **Vercel preview environment variables** (never commit actual values):

```ini
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=
```

6. Rebuild the Vercel preview and run the live Google sign-in suite in Android Chrome, iOS Safari and desktop. Test account A versus account B, logout, import/export, reset from a second device, disabled storage, network loss and quota exhaustion.
7. Update the site's privacy notice to describe Firebase Authentication's browser session persistence and Firestore score storage, including account deletion procedures, before opening registration to general users.

## Important safety rules built into the feature

- Guest learning is always free and stores scores locally. Sign-in never requires Google Drive, Gmail or Contacts permissions.
- **Never silently transfer guest scores into a Google account**, including on shared devices. Once signed in, the learner can explicitly choose **Import guest progress**. Guest data is retained if an upload fails.
- Google account scores are isolated by authenticated UID. Firestore Security Rules validate owner access, recognized lesson IDs and safe score values.
- When a user resets a cloud account, its `generation` increments. A different device with stale cached scores must respect the reset instead of resurrecting them.
- Existing portable JSON backup export/import is retained, and quiz retries must not increase XP more than the current best score.
- Nothing in this integration enables live pattern publishing, Google indexing, email marketing or advertising scripts.

## Review / deployment gates

- Source-level tests are not proof of Firestore rules behavior. Run local tests and both GitHub CI browser workflows on the exact branch.
- Do **not** flip `NEXT_PUBLIC_FIREBASE_*` on until an actual Google Firebase project is connected, rules are deployed and independently checked. Keep the preview usable as a free guest Academy.
