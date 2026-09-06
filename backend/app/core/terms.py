"""The published version of the terms of agreement an account accepts to register.

A date rather than a number, because what matters when a dispute arrives is *which* wording the
researcher agreed to and when it was in force. The register endpoint refuses any other value, so
a client that has not loaded the current terms cannot record an acceptance of them: the alternative
— trusting a boolean from the browser — records that someone ticked a box, not what they read.

Bump this whenever the terms text in the frontend changes. Existing accounts keep the version they
accepted; nothing re-prompts them, which is a product decision to make when the terms first change
materially rather than a behaviour to guess at now.
"""

TERMS_VERSION = "2026-09-06"
