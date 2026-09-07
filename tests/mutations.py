"""mutgate's own contracts, checked by mutgate in CI (the tool eating its own cooking)."""

from mutgate import Mutation

TESTS = ["tests/test_mutgate.py"]
PATHS = ["src"]

MUTATIONS = [
    Mutation("apply-ignores-count", "src/mutgate/core.py",
             old="        if found != m.count:", new="        if found == 0:",
             fires=("test_not_applied_when_old_is_absent_or_ambiguous",),
             note="an ambiguous `old` would be replaced everywhere and reported as applied"),
    Mutation("overreach-is-ok", "src/mutgate/core.py",
             old='        return Verdict(m, "OVERREACH", fired_t, missing, unexpected)',
             new='        return Verdict(m, "OK", fired_t, missing, unexpected)',
             fires=("test_overreach_is_the_two_copies_tell",)),
    Mutation("invisible-never-visible", "src/mutgate/core.py",
             old='        return Verdict(m, "VISIBLE" if fired else "OK", fired_t)',
             new='        return Verdict(m, "OK", fired_t)',
             fires=("test_visible_when_an_invariance_breaks",)),
    Mutation("baseline-not-checked", "src/mutgate/core.py",
             old="        if failed:\n            report.baseline_failed = tuple(failed)\n            return report",
             new="        if False:\n            report.baseline_failed = tuple(failed)\n            return report",
             fires=("test_red_baseline_aborts_before_any_mutation",),
             may_fire=("TestVerdicts",)),
    Mutation("no-restore", "src/mutgate/core.py",
             old="                    sb.restore(m, original)", new="                    pass",
             fires=("test_working_tree_is_untouched_and_restored_between_mutations",),
             may_fire=("test_cli_run_and_list",),
             note="the CLI test runs two mutations in sequence and sees the unrestored file too"),
    Mutation("error-reads-as-fired", "src/mutgate/core.py",
             old="    if rc in (2, 3, 4, 5) and not fired:\n        why", new="    if False:\n        why",
             fires=("test_error_when_the_mutation_does_not_compile",)),
    # the review of the first commit (2026-09-07): three silent false passes in the checker
    Mutation("summary-gate-off", "src/mutgate/core.py",
             old="    if rc == 1 and not fired:\n        # the gate", new="    if False:\n        # the gate",
             fires=("test_suppressed_summary_is_an_error_not_a_verdict",),
             note="review item 2: pytest exit 1 with nothing readable must be ERROR"),
    Mutation("string-fires-accepted", "src/mutgate/core.py",
             old="            if isinstance(val, str):", new="            if False:",
             fires=("test_a_bare_string_or_empty_fragment_is_refused",),
             note="review item 3: a bare string would match everything"),
    Mutation("only-typo-ignored", "src/mutgate/core.py",
             old="        if unknown:\n            raise ValueError", new="        if False:\n            raise ValueError",
             fires=("test_unknown_only_name_and_empty_list_are_errors",),
             may_fire=("test_cli_run_and_list",)),
    Mutation("sandbox-dir-unresolved", "src/mutgate/core.py",
             old='        self.dir = Path(tempfile.mkdtemp(prefix="mutgate-")).resolve()',
             new='        self.dir = Path(tempfile.mkdtemp(prefix="mutgate-"))',
             fires=("test_sandbox_survives_a_symlinked_tmpdir",),
             note="review item 1: a symlinked TMPDIR failed the containment check"),
]
