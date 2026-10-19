# Stitch Atlas — Free Google sign-in and progress sync

Status: **Implemented but OFF until a dedicated Firebase project is connected**.
No account is required to use the Academy; everything continues in guest/local mode.

## Cost-conscious infrastructure choice

- A dedicated **Firebase Spark** project with Firebase Authentication (Google provider) and Cloud Firestore (Standard, first database) provides a no-payment-method path for *this feature*.
- Documented Firestore free allowance: 1 GiB, 50k document reads/day, 20k writes/day, 20k deletes/day, 10 GiB monthly outbound data transfer. Exceeding Spark free limits can interrupt the relevant service until the quota resets. Never silently upgrade to Blaze.
- This does not replace the planned isolated editorial/CMS database. Firebase is used for account-owned **Academy progress only**.
- User content lives at exactly \`academyProgress/<Firebase Authentication UID>\`; **no email, name, photo or Google access token is written to Firestore**.

## Set up (requires connection to the Firebase account)

1. Create a dedicated Firebase project, e.g. "stitch-atlas-academy". Choose **Spark / no billing**. Do not share Firebase resources with RecetaGenial or RecetaDolce.
2. Register a **Web App** under Firebase project settings and copy its public web SDK parameters (apiKey, authDomain, projectId, appId). No service account credential or private key.
3. In **Authentication → Sign-in method**, enable the **Google** provider. Configure an appropriate support email; only request minimal default \`openid/profile/email\` through Firebase.
4. **Authentication → Settings → Authorized domains**: allow exactly the chosen stable Stitch Atlas preview/production hostname. Vercel builds use changing hosts; do not wildcard-authorize all \`vercel.app\`. The stable custom site hostname should be added when purchased. Validate login first with approved test accounts.
5. Create a **Cloud Firestore Standard** database in a suitable supported region; select production rules, not public test-mode access. Deploy the checked-in \`firestore.rules\` from this subdirectory using \`firebase deploy --only firestore:rules --project <dedicated-firebase-project-id>\` (the official Firebase CLI must be connected/authenticated). This file denies everything except account-owned progress documents.
6. In the **separate Stitch Atlas Vercel project**, set these **four public** env vars for preview, from the same Firebase Web App:
   - \`NEXT_PUBLIC_FIREBASE_API_KEY\`
   - \`NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN\` (usually \`<project-id>.firebaseapp.com\`)
   - \`NEXT_PUBLIC_FIREBASE_PROJECT_ID\`
   - \`NEXT_PUBLIC_FIREBASE_APP_ID\`
7. After rules are deployed and domain authorized, run the automated suites below, sign in on two test devices, pass quizzes and verify merged scores and per-user isolation. Do not delete either recipe Supabase project or enable any paid plan.

These Firebase Web App identifiers are intentionally public. **Never** put Firebase service-account keys, refresh tokens, billing credentials or Admin SDK in \`NEXT_PUBLIC_*\`.

### Development switches / safe fallback

With any of the four values missing, the application does not initialize Firebase Auth or Firestore. It shows a quiet "cloud saving is not connected" message and uses existing local progress. If cloud reads/writes fail due to connectivity/quota, the user can continue lessons and retry sync later. Quizzes never require Google login.

### User privacy & data behavior

- **Guest → signed in:** merge private local progress with remote cloud data. Best scores win; points derive from unique completed lessons rather than counting events.
- **Signed in → signed out:** clear cached account-specific scores from the shared browser. Remote records are untouched.
- **Offline:** continue saving locally; on reconnection (or via Sync now) attempt a Firestore transaction.
- **Reset while signed in:** request cloud deletion of quiz progress *in the same user document*; only clear local progress if the cloud reset succeeds.
- **Multiple tabs:** localStorage storage events update the visible progress. No cross-device real-time database listeners or polling; sync at sign-in, finished quizzes, explicit button and reconnect.
- **Backup:** existing offline JSON export remains useful while no account is connected.
- **Limitations:** progress is self-reported client state, not examination/certification evidence. A technically capable user can forge their own best score; cloud rules prevent reading/writing someone else's data, not faking personal quiz answers. No public leaderboard or skill credential is derived from these records.
- **Privacy compliance:** add an accurate privacy notice with the Firebase vendor, categories of data (UID, email displayed in session, lesson scores), retention, and user account deletion process before activating accounts for the public. Do not imply GDPR compliance before operational review.

### Run

\`\`\`sh
cd apps/stitch-atlas
npm install
npm run test:cloud
npm run test:academy
npm run test:editorial
npm run test:guides
npm run build
\`\`\`

**Rules integration gate:** automated source tests verify critical clauses but do **not** replace Firebase Emulator security-rule tests or real separate-account writes. Before production activation, run \`firebase emulators:exec\` with \`@firebase/rules-unit-testing\` or equivalent to prove cross-user reads/writes forbidden and owner writes allowed with server timestamps. Until then, consider the cloud integration **built but not activated/production-verified**.

**References**: https://firebase.google.com/pricing , https://firebase.google.com/docs/firestore/pricing , https://firebase.google.com/docs/auth/web/google-signin , https://firebase.google.com/docs/firestore/security/rules-fields
