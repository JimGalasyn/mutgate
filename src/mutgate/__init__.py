"""mutgate — named mutations as contracts on a test suite.

    from mutgate import Mutation
    MUTATIONS = [
        Mutation("keep-larger", file="pkg/engine.py",
                 old="if birth[a] >= birth[b]:", new="if size[a] >= size[b]:",
                 fires=("TestElderRule",)),
        Mutation("tie-to-higher-index", file="pkg/engine.py",
                 old="(birth[a], -a) >= (birth[b], -b)", new="(birth[a], a) >= (birth[b], b)",
                 invisible=True),          # an invariance: must fire nothing
    ]

Then `mutgate run tests/mutations.py`. Each mutation is applied in a sandbox copy, the
tests run, and the contract judged: OK, DECORATION (a named guard did not fire),
OVERREACH (something outside the contract fired — two copies of one convention?),
VISIBLE (an invariance was broken), NOT_APPLIED (the text was not found), ERROR.
"""

from .core import Mutation, Report, Verdict, load, run

__version__ = "0.1.1"
__all__ = ["Mutation", "Report", "Verdict", "load", "run", "__version__"]
