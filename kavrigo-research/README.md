# kavrigo-research

Notebooks, experiments, feature studies, evaluation sets and leakage audits.

Rules:

- **No production credentials, ever.** Research uses public, mock, or licensed development data.
- Notebooks never become production code. Promote logic into tested libraries in
  `kavrigo-engine/libs/` and import it back.
- Every experiment records its dataset manifest, feature version, seed and artifact hashes
  (`MASTER_BUILD_SPEC.md` §41).
- Backtest results reported here must state costs, benchmark, and whether they are in-sample.
- Point-in-time correctness is mandatory: no revised provider history, no future candles, no
  news timestamped after the decision (`MASTER_BUILD_SPEC.md` §12.3).

```text
notebooks/  experiments/  feature-studies/  datasets/  evals/  leakage-audits/  reports/
```
