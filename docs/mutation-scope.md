# Runtime mutation scopes

Every adopted candidate now records `mutation_scope` evidence in the formula
ledger, with the parent and child revision, runtime grant, typed verdict, basis,
and canonical role footprint. A model-selected tool name or extra argument
cannot grant permission: `planner_tool:repair_tex` is still a proposed candidate;
only the result of the actual deterministic `repair_tex` execution receives a
syntax repair grant.

| Runtime transition | Invariant |
| --- | --- |
| Syntax repair | The pinned raw KaTeX structure must remain identical. A malformed parent may receive only trailing closing braces, with its existing bytes retained and the child reliably parsed. Other recovery is review required. |
| Completion | All tokens of the original user prefix, including commands, delimiters, grouping, scripts and bounds, must remain an exact leading sequence. The provisional suffix may change. The deterministic shortcut uses the same invariant. |
| OCR role review | Only complete role paths supplied by a trusted runtime caller may change. `root[0].denominator` authorizes that fraction's denominator, and cannot authorize its numerator or another fraction. Public OCR currently grants no uncertain roles. |
| NL candidate synthesis | A provisional translation may be regenerated. Its intent is explicitly `NOT_CHECKED`; this grant is not a semantic correctness or equivalence claim. Request anchors remain a separate runtime policy. |

The shared raw AST canonicalizer preserves denominator/numerator roles, integral
rank, bounds, scripts, fraction bars, root indices, fonts and matrix structure.
It retains the pinned KaTeX 0.17.0 allowlist used by strict evaluation. Unknown
nodes, macros, unrepresented text/presentation, parse failure, depth/size limits,
and degraded role alignment cannot silently authorize a mutation.

Unauthorized or uncertain transitions remain visible as proposed revisions, but
cannot automatically commit. Compile validity can still be true; `committed`
remains false and the stop reason is `mutation_scope_review_required`. Restoring
the final text later does not erase an earlier scope violation. This first
implementation provides no full AST serializer and no human approval bypass;
revision-bound review is a separate capability.

The offline tests contain role drift counterexamples for denominator, numerator,
upper/lower bounds, integral rank, subscript, superscript and root index. Runtime
tests exercise trusted OCR role grants, forged planner grants, deterministic
completion, commit rejection and a later restoration. Structural matcher tests
also run after extracting its canonicalizer into the installable package.
