## Summary

Describe the changes in this pull request and the problem they solve.

## Checklist

- [ ] Code passes `ruff check .` with zero errors
- [ ] All unit & UI tests pass (`QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v`)
- [ ] DSP / audio changes verified for zero NaN/Inf outputs and real-time latency (< 16 ms budget)
- [ ] Bilingual UI strings updated in `clearmic/i18n.py` (EN + TR) if UI text changed
- [ ] Documentation / `CHANGELOG.md` updated where applicable
