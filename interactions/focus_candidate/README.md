# Focus Candidate Interaction

`focus_candidate` is an independently registered, auditable Interaction for
researching one pending Focus recommendation. It exact-composes Conversation
by reference and owns only the candidate-specific evidence, next-gap,
confirmation, and completion contract.

Play is read-only. Confirmed completion delegates to the canonical
candidate-research source authority and leaves the recommendation pending.
Only the existing approval/autopilot path creates a Focus.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py focus-candidate-evals --json
```
