# Timeline goldens

`timeline_fixtures.json` contains synthetic placements: an unknown with its
kind, its label, the anchors the person has actually supplied, and the years
those anchors and the person's own words make available — plus one row per
turn carrying the turn's `{timeline_stage}`, the playbook rung the probe is
on, and the `placed` value a correct model would produce after BOTH validation
layers. `timeline_sample_predictions.json` is the deterministic recorded seat —
the reply text and the raw, pre-validation `placed` object for each of those
turns. Live seating uses the same fixtures and gates and skips loudly without a
configured provider.

`timeline-skeleton-episode` is the one that matters most: a birthday, then the
places lived by age, which dates most of a timeline by inference and makes
every later probe cheap. It is the life-history calendar (Freedman et al.
1988) run as a conversation.
