# 0001 — Two packages: `polybedrock-core` and `polybedrock-ui`

**Status:** Accepted · **Date:** 2026-09-05

## Context

PolyShield and PolyScour are both Python 3.11 + CustomTkinter Windows desktop
applications. PolyShield already contained working, tested implementations of
almost everything PolyScour needs a foundation for. The alternative — building
PolyScour in C#/WPF as originally proposed — would have discarded that and
reduced the relationship between the two products to a socket call.

## Decision

Extract shared code into **two** independently versioned packages in one
repository:

- `polybedrock-core` — Windows platform code, **no UI dependency at all**
- `polybedrock-ui` — CustomTkinter theming and shared widget behaviour

`polybedrock` is a PEP 420 namespace package so both contribute to it. Dependency
flows one way: ui may import core, never the reverse.

## Why two and not one

A single package would predictably degrade into a mixture of Win32 calls,
SQLite, PowerShell, colour tokens and widgets. The split costs nothing at
extraction time and cannot be done cheaply later, once both applications import
from it.

## Why one repository

One CI system, one place to review a change that spans both. But **independent
versions**: a trivial `polybedrock-ui` change must not force a new semantic release
of the Windows substrate.

## Consequences

- PolyBedrock is infrastructure. Its own suite passing is not sufficient evidence
  that a change is safe; CI must run the consumers' suites at the revisions
  PolyBedrock declares support for, rather than at whatever is on `master`.
- Neither distribution may ship `src/polybedrock/__init__.py`. Guarded by
  `core/tests/test_package_boundary.py`, because the failure only appears once
  both packages are installed.

## Addendum — the consumer gate, pinned (2026-09-07)

The consequences above said CI "must run the consumers' suites at the revisions
PolyBedrock declares support for, rather than at whatever is on `master`." It
did not. The `consumers` matrix listed **PolyShield only**, at `ref: master`,
carrying a `# pin to a tag once PolyBedrock declares support` note — so
PolyScour, a declared consumer, was not gated at all and a substrate change
could break it silently.

### What changed

**PolyScour joins the matrix.** It installs differently from PolyShield — no
`requirements-ci.txt`, and its `pyproject.toml` names `polybedrock-core`/`-ui`
as ordinary dependencies that exist on no index — so the matrix now carries an
`install:` command rather than only a deps file. PolyScour must install the
local substrate *first* or pip goes looking on PyPI; PolyShield must install
its own deps first, because it declares polybedrock from git URLs that would
otherwise overwrite the substrate under test. The final `pip install -e` of
PolyBedrock is unconditional for both and settles it either way — without it
this stage could report a green consumer against a PolyBedrock that is not the
one being changed, which is the single result it must never produce. A cheap
`print(polybedrock.__path__)` step proves the override won.

**Both consumers are pinned to a commit.** Testing PolyBedrock@HEAD against
consumer@`master` is two moving branches proving each other: it can go green
for a pair of mutually-dependent changes that would not work against any
released version of either, and it makes a red run ambiguous between "the
substrate broke the consumer" and "the consumer was already broken". A commit
answers both questions. No tags exist yet, so these are SHAs; they become tags
when there are tags.

The pins are **bumped deliberately**, as the act of declaring support for a
newer consumer revision. Automating the bump would restore exactly the moving
target this removes.

### Versioning, and what a bound means

PolyBedrock's two packages version independently (above). What the numbers mean:

| Change | Bump |
|---|---|
| Breaking a core API a consumer calls | major |
| New backward-compatible capability | minor |
| Fix with no API change | patch |

A consumer's dependency declaration and its compatibility *claim* are two
different things and must agree. PolyScour now declares
`polybedrock-core>=0.1,<0.2`; the upper bound is not semver ritual but a
statement that support intentionally stops at this API generation, so
PolyBedrock 0.2 arriving becomes a deliberate consumer update rather than a
silent break. The pinned run above is what verifies the claim at a concrete
point instead of assuming it — a declared range only ever tested at one
revision is a range in name only, and a full version × consumer × Python matrix
is not worth building at two consumers.

### Addendum — PolyShield closes the same gap (2026-09-07)

The paragraph that stood here said PolyShield still declared
`polybedrock-core @ git+https://…` with no revision and no bound, and that
fixing it belonged in its own repository. It now has: PolyShield pins all three
of its declaration sites — `requirements.txt`, `requirements-ci.txt` and
`build.ps1` `$RUNTIME_PKGS`, the last of which bakes the substrate into the
interpreter that ships inside its installer — and its 896-test suite passes
against the result with no existing test edited.

The bound could not be written the way PolyScour writes it, and the reason is
worth recording because it will recur for any consumer installing from git.
PolyBedrock is not on PyPI, so it arrives as a PEP 508 **direct reference**, and
a direct reference may not carry a version specifier:
`polybedrock-core>=0.1,<0.2 @ git+https://...` does not parse. PolyScour can
declare the range because it names the packages as ordinary dependencies;
PolyShield cannot.

So PolyShield asserts the range instead, in `tests/test_substrate_pin.py`,
against the metadata of whatever is actually installed. That location is better
than a declaration would have been, for a reason specific to this workflow: the
`consumers` stage deliberately installs the substrate under test *over* whatever
the consumer declared, which makes a consumer's own pin inert here. The
assertion is the only thing left that can object — so a PolyBedrock bump past
0.2 now turns the PolyShield job red on purpose instead of being discovered
downstream. The PolyShield pin in the matrix was bumped to that revision in the
same breath, because the gate does not exist until this repository checks out a
consumer that carries it.

The same test also guards the drift three copies of one URL invite: an unpinned
site, a site that stopped declaring a package it should, or three sites naming
different revisions.

### CI convergence

PolyShield's workflow has been the de-facto template — PolyScour's was brought
up to it in the same pass, and this one with it (action majors off the
deprecated Node 20, `push`/`pull_request` parity, `permissions`, `concurrency`).
Four repositories hand-copying CI will drift. The destination is a shared
`docs/CI.md` here that both products link to, covering portable GUI invariants
versus machine-specific visual baselines — the reasoning PolyScour currently
carries as a comment block copied from PolyShield. Worth doing when a third
copy would otherwise be made, not before.
