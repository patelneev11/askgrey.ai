# Patent search fixtures

The USPTO Open Data Portal search API (`https://api.uspto.gov/api/v1/patent/applications/search`)
requires a free `X-API-KEY`, and no key was available while this module was written: an
unauthenticated request to that endpoint answers `401`. These fixtures were therefore built by
hand from the endpoint's published response schema (`totalNumFound` plus a
`patentFileWrapperDataBag` of application records with an `applicationMetaData` object), not
recorded from a live call.

What that means for the tests:

- The **shape** is the documented ODP shape, which is what the parser is being tested against.
- The **content** is illustrative, not a real search result, and no code path presents fixture
  content to a user.
- `search_page1.json` also exercises the awkward parts of real records: a published-but-not-yet
  granted application with no `patentNumber` or `grantDate`, an applicant carried as an
  organization name, an inventor carried as first/last name parts, and CPC symbols in both
  supported spellings.

If a key is configured later, re-record these files from a real query and drop this note.
