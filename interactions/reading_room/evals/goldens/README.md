# Reading Room goldens

`reading_room_fixtures.json` contains synthetic sessions: what the person has
in front of them (`inventory`), the stage of each turn, the anchors the
episode showed, and the `placed` / `landmark` values a correct model would
produce after BOTH validation layers.
`reading_room_sample_predictions.json` is the deterministic recorded seat —
the reply text and the raw, pre-validation fields for each of those turns.
Live seating uses the same fixtures and gates and skips loudly without a
configured provider.

`reading-room-album-dates-by-photo` is the one that matters most: a shoebox
session where the evidence is the photograph itself, and the record that comes
out carries `basis: photo` with real bounds, because a contextual date is a
window by construction and the system says so on the record it writes
(`system/research/go-deep.md` §5.1, §11.21).

`reading-room-document-beats-memory` is the etiquette case: a report card says
June, the person remembered spring, and the reply attributes the challenge to
the SOURCE rather than to the person. Both claims survive; `document` outranks
`stated` in `chronology.BASIS_WEIGHT`, so the paper is what the timeline shows
and the memory is kept beside it.

`reading-room-mom-on-the-phone` is the `relative` basis end to end: the person
relays what their mother just said, the record carries her in provenance as
`witness:mom`, and the confidence is capped at `approximate` because a proxy
report is meant to be used WITH the index report, not instead of it
(Straughen et al. 2013, §6.4).

`reading-room-i-will-find-out` is the deferral test. "That box is at my
sister's" ends the item, and the reply creates no reminder, no follow-up and
no list — v196 deleted a deferral machine deliberately and the rule stands.

`reading-room-opens-with-the-inventory` and
`reading-room-asks-for-the-address-grade` pin the two moves the lane exists
for: the room before the memory, and the grade of detail that unlocks the
derivations (a school's address → its district → exact years, §5.3).
