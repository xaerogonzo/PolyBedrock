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
