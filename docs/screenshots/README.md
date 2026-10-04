# README screenshots

Captured from [https://bryanzane.com/community-voices/](https://bryanzane.com/community-voices/) in a fresh, signed-out Chromium session.
These are public production pages and their real assets, with no mocked responses.
The live deployment can differ from the current checkout. Captured October 4, 2026.

```sh
cd docs/screenshots && npm ci && npx playwright install chromium && npm run capture
```

Requires Node.js, network access, and `cwebp` (libwebp). No local app server is needed.
The script uses a 1440 × 580 viewport, waits for visible images and fonts, and
writes WebP files below 300 KB. It does not sign in, publish content, or submit
AI prompts. Any typed text is a disposable sample. Public content can change
between captures.

## Content review

The screenshot shows the July 14–21 report overview and first topic. Its visible
text was reviewed on October 4, 2026: relevant gaming/technology discussion,
without coarse language, identifiable commenters, explicit imagery, or personal
contact details. Lower discussion cards are outside the frame; report wording
is not rewritten or censored. This is a UI example, not a fact-check of its claims.

The script selects that week and checks the rendered report text against a
reviewed SHA-256 fingerprint before writing an image. If the text changes, it
stops and preserves the existing screenshot. Do not update the fingerprint just
to make capture pass: read the new content and inspect the final frame first.
Also recheck framing after layout changes. A matching text fingerprint cannot
review imagery or CSS changes. Do not click Regenerate to obtain a new example.

README images are committed files. They do not refresh when the live feed changes.
