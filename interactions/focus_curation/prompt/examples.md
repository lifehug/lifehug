# Examples — curated verdicts, good and bad

Synthetic content only — no real vault data, no references to any real
person's story. Every example below is invented for this file. Each names
the specific rule it demonstrates or violates.

## Merge: genuine token-subset identity (rules 3, 4, 5)

**Handed pending ideas:** `rec-betty-jo` ("Betty Jo", person, evidence: 2
answers), `rec-betty-jo-taylor` ("Betty Jo Taylor", person, evidence: 3
answers, one explicitly says "my grandma, Betty Jo Taylor").

**GOOD verdict:**
> `{"merge": [["rec-betty-jo-taylor", "rec-betty-jo"]], "map_to_focus": {}, "keep": []}`
> Canonical first (rule 4): "Betty Jo Taylor" is the fuller name and one
> piece of evidence explicitly ties the two together. Genuine identity
> evidence, not just topical overlap (rule 5).

**BAD verdict — wrong order:**
> `{"merge": [["rec-betty-jo", "rec-betty-jo-taylor"]], "map_to_focus": {}, "keep": []}`
> Violates rule 4 — the shorter, less complete name is listed first, so the
> runtime would canonicalize on "Betty Jo" instead of the fuller identity.

## Keep: topical overlap without identity evidence (rules 5, 8)

**Handed pending ideas:** `rec-fear` ("Fear", theme, evidence: 4 answers
about anxiety), `rec-money-stress` ("Money Stress", theme, evidence: 2
answers about financial pressure).

**GOOD verdict:**
> `{"merge": [], "map_to_focus": {}, "keep": ["rec-fear", "rec-money-stress"]}`
> Related subjects, but no identity evidence they're the same theme under
> two names — rule 5 forbids merging on topical overlap alone; rule 8 makes
> `keep` the correct default here.

**BAD verdict — merges on topic alone:**
> `{"merge": [["rec-fear", "rec-money-stress"]], "map_to_focus": {}, "keep": []}`
> Violates rule 5 — "money stress can cause fear" is a thematic relationship,
> not evidence they are one identity.

## map_to_focus: the idea IS the existing Focus (rule 6)

**Handed:** `rec-mom` ("Mom", person, evidence references "my mother,
Karen"), `existing_focuses: {"karen": "Karen"}`, roster_context shows the
"Karen" roster entry's aliases include "Mom", "Mother".

**GOOD verdict:**
> `{"merge": [], "map_to_focus": {"rec-mom": "karen"}, "keep": []}`
> The roster's settled aliases (rule 7) confirm "Mom" and "Karen" are the
> same identity — the idea IS the existing Focus by another name.

**BAD verdict — invents a slug not in existing_focuses:**
> `{"merge": [], "map_to_focus": {"rec-mom": "mother-figure"}, "keep": []}`
> Violates rule 1 — `"mother-figure"` was never handed as a valid slug in
> `existing_focuses`.

## Malformed: incomplete partition (rule 2)

**Handed:** `rec-a`, `rec-b`, `rec-c`.

**BAD verdict — drops rec-c:**
> `{"merge": [["rec-a", "rec-b"]], "map_to_focus": {}, "keep": []}`
> Violates rule 2 — `rec-c` appears in no bucket. The runtime treats this
> whole verdict as malformed and applies nothing (no partial application).

## Malformed: a reason field (output constraints)

**BAD verdict:**
> `{"merge": [], "map_to_focus": {}, "keep": ["rec-a"], "reason": "no strong evidence either way"}`
> The schema has exactly three keys. Adding a fourth — however reasonable
> the text — is malformed, per the no-reason-capture decision (`README.md`
> §4).
