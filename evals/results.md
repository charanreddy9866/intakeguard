# Eval results

Generated 2026-11-20 with `python -m evals.compare rules`.

| extractor | dataset | document_type | claimant_id | document_date | needs_review | exact | errors | p50 ms | tokens/doc | cost / 1k docs |
|---|---|---|---|---|---|---|---|---|---|---|
| `rules` | core | 100% | 100% | 100% | 100% | 100% | 0/30 | 0 | 0 | $0 |
| `rules` | hard | 53% | 80% | 73% | 77% | 33% | 0/30 | 0 | 0 | $0 |

Fields are scored after guardrails, i.e. on what would actually be stored. `needs_review` checks that a document is sent to a human exactly when it should be. `errors` counts documents where the provider returned no usable answer (timeouts, rate limits); a row with errors does not measure model accuracy.

<details><summary>Misses</summary>

- `rules` hard H01 claimant_id: expected `C-101`, got `None` ['no_claimant']
- `rules` hard H01 needs_review: expected `False`, got `True` ['no_claimant']
- `rules` hard H02 document_type: expected `intake_form`, got `other` []
- `rules` hard H02 document_date: expected `2026-10-14`, got `None` []
- `rules` hard H03 document_type: expected `medical_record`, got `other` ['no_claimant']
- `rules` hard H03 claimant_id: expected `C-102`, got `None` ['no_claimant']
- `rules` hard H03 document_date: expected `2026-03-14`, got `None` ['no_claimant']
- `rules` hard H03 needs_review: expected `False`, got `True` ['no_claimant']
- `rules` hard H04 document_type: expected `id_document`, got `other` []
- `rules` hard H05 document_type: expected `medical_record`, got `None` ['claimant_not_in_tenant']
- `rules` hard H05 claimant_id: expected `C-102`, got `None` ['claimant_not_in_tenant']
- `rules` hard H05 document_date: expected `2026-05-20`, got `None` ['claimant_not_in_tenant']
- `rules` hard H05 needs_review: expected `False`, got `True` ['claimant_not_in_tenant']
- `rules` hard H06 claimant_id: expected `C-205`, got `None` ['no_claimant']
- `rules` hard H06 needs_review: expected `False`, got `True` ['no_claimant']
- `rules` hard H07 document_date: expected `2026-10-27`, got `None` []
- `rules` hard H08 document_type: expected `medical_record`, got `other` []
- `rules` hard H08 document_date: expected `2026-09-09`, got `None` []
- `rules` hard H11 document_type: expected `None`, got `intake_form` []
- `rules` hard H11 claimant_id: expected `None`, got `C-101` []
- `rules` hard H11 needs_review: expected `True`, got `False` []
- `rules` hard H12 needs_review: expected `True`, got `False` []
- `rules` hard H14 document_type: expected `id_document`, got `other` []
- `rules` hard H15 document_type: expected `medical_record`, got `other` []
- `rules` hard H16 document_date: expected `2026-11-02`, got `None` []
- `rules` hard H17 document_type: expected `medical_record`, got `other` []
- `rules` hard H18 claimant_id: expected `C-205`, got `None` ['no_claimant']
- `rules` hard H18 needs_review: expected `False`, got `True` ['no_claimant']
- `rules` hard H19 document_type: expected `None`, got `intake_form` ['no_claimant']
- `rules` hard H19 document_date: expected `None`, got `2026-05-05` ['no_claimant']
- `rules` hard H24 document_type: expected `medical_record`, got `other` []
- `rules` hard H24 document_date: expected `2026-09-09`, got `None` []
- `rules` hard H25 document_type: expected `id_document`, got `other` []
- `rules` hard H28 document_type: expected `medical_record`, got `other` []
- `rules` hard H30 document_type: expected `id_document`, got `other` []

</details>
