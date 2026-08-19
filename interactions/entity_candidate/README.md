# Entity Candidate Interaction

`entity_candidate` is an independently registered, auditable Interaction for
researching one entity roster candidate. It exact-composes Conversation
by reference and owns only the candidate-specific evidence, next-gap,
confirmation, and completion contract.

Play is read-only. Confirmed completion delegates to the canonical
candidate-research source authority and leaves the entity roster pending.
Only independent entity eligibility or an owner graduation can create a page.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py entity-candidate-evals --json
```
