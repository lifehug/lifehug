# Router extension — candidate placement signal

The inherited Conversation router taxonomy still describes inbound chat
mechanics. For an engaged Question Candidate, also distinguish whether the
exact current user turn contains only placement information
(`placement_only`), substantive answer content without usable placement signal
(`answer`), or both (`mixed`). This metadata never authorizes deletion or a
lifecycle transition. When uncertain between answer and mixed, preserve the
turn and choose `answer`; the worker may defer placement.
