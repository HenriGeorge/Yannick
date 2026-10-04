---
name: wait-test
description: 'Discover which plan steps can run in parallel by applying the "wait test", then emit a ## Parallelization callout for parallel_gate to enforce. Use when writing or reviewing a plan with ≥2 tasks, or on "can this parallelize", "wait test", "which steps can run at once".'
---

# Wait Test

`parallel_gate` **enforces** a plan's `## Parallelization` callout (blocks same-batch file overlap),
and `agent-delegation.md` documents its format — but nothing helps you **discover** which tasks are
actually independent. Plans default to a sequential chain even when steps don't depend on each other
(the "false sequential dependency"). This skill is the discover front-end: it finds the parallelism,
you declare it, `parallel_gate` enforces it.

## When to use

- Writing or reviewing an implementation plan with **≥2 tasks**.
- "Can this parallelize", "wait test", "which steps can run at once", "why is this all sequential".
- NOT a gate — it never rewrites a plan. It suggests a callout; `parallel_gate` is the enforcement.

## The wait test

For each task, ask one question:

> **Does this task consume a prior task's output or file?**
>
> - **No** → it does not need to wait. Parallel candidate.
> - **Yes** → it must wait on that task. Sequential edge.

A task waits only on a *real* data/file dependency, not on the order it happens to be listed in.

## Workflow

1. **Apply the wait test to every task** — build the depends-on edges (yes = edge, no = none).
2. **Group the independents into batches** — candidates with **disjoint files** go in the same
   batch. Two tasks in one batch MUST NOT share any file path in their **Files:** blocks
   (Create/Modify/Add/Delete/Edit/Test or bare path bullets) (#915); if they touch the same
   file, they are NOT independent for batching — split them across batches. This is exactly the
   invariant `parallel_gate` checks, so respecting it here means the gate passes.
3. **Cap each batch at ≤5 tasks** — more than five concurrent branches is usually false confidence
   (the "graph engineering" rule of thumb). Soft guidance: exceed it only with a stated reason.
4. **Emit the callout** — machine-parseable, batches by task id:

   ```
   ## Parallelization
   - Batch 1: T1, T3
   - Batch 2: T2
   ```

   Tasks left out of every batch run sequentially. If the wait test finds a real edge into every
   task, say so explicitly instead — **"fully sequential: every task consumes the prior's output"** —
   rather than inventing a batch.

## Verify

- Every same-batch pair owns disjoint file paths (Create/Modify/Add/Delete/Edit/Test or bare path-like bullets) (else `parallel_gate` BLOCKs).
- No batch exceeds 5 tasks (or carries a one-line reason if it does).
- The suggested callout parses as the `## Parallelization` format above — paste it into the plan and
  let `parallel_gate` confirm at commit time.

Pass = a callout `parallel_gate` accepts, or an explicit fully-sequential verdict. Fail = a batch
with overlapping files, or a claimed parallel that actually consumes a prior task's output.
