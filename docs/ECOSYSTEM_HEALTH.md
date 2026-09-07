# Ecosystem health check

Four repositories, three of them in one dependency graph. Run this at a phase
boundary, before a release, or after any pin moves — it is a checklist rather
than a job because most of it needs judgement, and the parts that do not are
one command each.

The point of the "against which revision" column is that without it, *green*
degrades into *the default branch happened to pass today*. That is the
master-vs-master trap the pinning policy exists to remove, and it reappears in
the health check if the revision goes unstated.

| Repository | Green when | Against which revision |
|---|---|---|
| PolyBedrock | core + ui suites pass, **and both consumers pass** | consumers at their pinned revisions |
| PolyShield | CI green on `master`, suite **unedited**, build works | its pinned PolyBedrock revision |
| PolyScour | CI green on both matrix legs, index present, app launches | its declared PolyBedrock range |
| TokenSave Manager | tests green, Retrofit state matrix and argv contract covered | n/a — development tooling, not in the product graph |

## Pin distance

**The consumer pins do not go stale loudly.** A stale pin produces a green
consumer job, quickly, against code nobody is shipping — invisible in exactly
the way a red run is not. It has happened: the PolyScour pin sat unmoved from
the commit that introduced it while two pull requests — five commits, including
an elevated helper — merged downstream, and nothing anywhere reported it. See `docs/adr/0001`, "The pins drift, and nothing here
notices".

So the number worth seeing is the **distance between each pin and its
consumer's `master`**:

```bash
python .github/scripts/pin_distance.py
```

Zero for both is the healthy state. Anything else is not a failure — a pin is
*meant* to lag while a consumer moves — but it is the size of what this
repository has not validated, and it should be a number someone chose rather
than one that accumulated.

### Why this reports rather than acts

Bumping a pin is the act of declaring support for a newer consumer revision, and
that decision stays deliberate. A pin that advances on its own is `ref: master`
with extra steps: it restores the two-moving-branches problem, and it makes a
red run ambiguous again between "the substrate broke the consumer" and "the
consumer was already broken".

What was missing was never automation. It was the number.

## Bumping a pin, when the distance says to

1. Read what the distance covers — `git log <pin>..master` in the consumer.
2. Open a PR in **this** repository that moves the `ref:` and says what the new
   revision contains. The consumer job in that PR is the validation.
3. One consumer per PR. Bumping both at once means a red run cannot be
   attributed to either, which is the ambiguity the pins exist to remove.
