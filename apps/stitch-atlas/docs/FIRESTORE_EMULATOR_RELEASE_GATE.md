# Firebase security integration tests for Stitch Atlas Academy

This suite makes **zero real Firebase project, billing, or Google-account changes**. A temporary `demo-stitch-atlas-rules` project is emulated on GitHub Actions, using the same Firestore rules intended for the optional Google sign-in feature.

## Why this is a release gate

Source-code string checks cannot prove Firestore enforces per-user privacy. The emulator test signs in as two simulated users, plus a guest, and asserts:

- Only the matching authenticated UID can read and write a progress document.
- List/search access is denied, as are all unrelated collections.
- Unknown lesson IDs, unsupported scores, unknown fields and forged timestamps are rejected.
- Intentional resets increment the cloud generation and clear scores together.
- Stale devices **cannot lower a newer generation**, skip a generation, or silently delete lessons without a reset.

The test does not prove real Google OAuth, deployment authorization, production Firestore credentials, or a finished user-data/privacy policy. Those remain separate gates.

## Run locally without a live Firebase account

Node.js 22+, Java 21+ and internet access for tooling:

```bash
cd apps/stitch-atlas
npm install
npx --yes firebase-tools@14.27.0 emulators:exec --project demo-stitch-atlas-rules --only firestore 'npm run test:firestore'
```

The dedicated GitHub workflow repeats this test on relevant changes. Do not deploy rules to a production Firebase project until the user selects and authorizes a dedicated account/project.
