# TEP dataset source selection status

Status: `PROVISIONAL`.

The active research discussion has superseded the earlier assumption that the Ricker `idv13.zip` would be the primary experimental dataset.

Current direction:

- primary benchmark candidate: Rieth et al. (2017), Harvard Dataverse V1, DOI `10.7910/DVN/6C3JR1`;
- focal fault: IDV(13);
- Ricker `idv13.zip`: historical/reference artifact only;
- generating new TEP simulations in MATLAB/Simulink: excluded from the primary plan by researcher preference;
- Reinartz et al. (2021): possible later robustness/external-validation source, not required for the initial experiment.

The existing `source_manifest.md` reflects the earlier Ricker intake stage and must not be interpreted as the current source-selection decision. The Rieth files still require direct download and binary/schema audit before the dataset is frozen.

Methodological ratification of subset selection, normal-reference construction, leakage controls, run sampling and detector-input variables is assigned to MECAI. See `rieth_dataset_intake.md`.
