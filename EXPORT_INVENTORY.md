# Export inventory

## Identificação

- Origem: `X:\PSQZA_TEP_LOCAL`
- Destino: `https://github.com/prefix325/experimento`
- Branch: `main`
- Gerado em: `2026-08-20T23:58:50Z`
- Commit da origem canônica: `3083558c1aac86508ed7e4fbc9f9b2b33696e701`
- SHA-256 do `FINAL_CAMPAIGN_MANIFEST`: `d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5`
- SHA-256 do SAP incluído: `a5ff532c9b0147b30c92d24432ca92e13ad6541f8a00920598572158ad811b5b`

As métricas abaixo descrevem o snapshot da origem. Os sete arquivos de documentação/política criados exclusivamente no espelho — incluindo este inventário — são enumerados separadamente e não entram nas contagens do snapshot de origem.

## Resumo do snapshot

| Métrica | Arquivos | Bytes | Tamanho aproximado |
|---|---:|---:|---:|
| Origem examinada | 14.243 | 5.651.490.169 | 5,263 GiB |
| Selecionado da origem | 7.887 | 16.687.594 | 15,91 MiB |
| Excluído da origem | 6.356 | 5.634.802.575 | 5,248 GiB |

## Categorias incluídas

| Categoria | Origem | Arquivos | Bytes | Motivo |
|---|---|---:|---:|---|
| Conteúdo versionado do repositório canônico + SAP | `repo/` | 247 | 2.583.385 | Código, documentação, governança, testes e artefatos congelados; `repo/.git` excluído |
| Manifests operacionais | `manifests/` | 9 | 88.505 | Provenance e auditoria |
| Logs pequenos de preparação | `logs/` | 8 | 33.225 | Diagnóstico de preparação |
| Metadados de dataset | `data/` | 5 | 12.735 | README, manifests e checksums sem payload |
| Licença/metadados de modelo | `models/` | 1 | 11.343 | Licença sem pesos |
| Artefatos leves de auditoria de resultados | `results/` | 7.571 | 13.766.900 | Status, markers, manifests, comandos, summaries e provenance |
| Aceitação/observabilidade técnica | `results/technical_*` | 46 | 191.501 | Evidência técnica pequena e não científica |

## Categorias excluídas

| Categoria | Origem | Arquivos | Bytes | Motivo |
|---|---|---:|---:|---|
| Pesos de modelo | `models/` | 1 | 4.683.073.536 | Binário GGUF pesado; não usar Git LFS neste espelho |
| Datasets brutos/preparados | `data/` | 72 | 519.250.967 | Payload científico, CSV/RData/archives |
| Resultados científicos brutos ou volumosos | `results/` | 3.365 | 391.352.706 | Métricas/decisões por janela, outputs e logs científicos |
| Cache local de ferramentas | `tools/` | 2.772 | 38.569.365 | Cache `uv`, reinstalável e não reprodutivo |
| Metadados Git aninhados | `repo/.git/` | 74 | 1.698.504 | O espelho tem histórico próprio e não incorpora o repositório interno |
| Cache/untracked não selecionado do repo | `repo/` | 72 | 857.497 | `__pycache__`, `.pytest_cache` e derivados |

## Arquivos criados somente no espelho

1. `.gitignore`
2. `README.md`
3. `data/README.md`
4. `models/README.md`
5. `results/README.md`
6. `EXPORT_INVENTORY.md`
7. `EXPORT_INVENTORY.json`

## Regras de seleção

- Nenhum arquivo acima de 20 MiB pode ser staged.
- Nenhum peso de modelo, dataset bruto, imagem/volume Docker, cache ou `.git` aninhado pode ser staged.
- De `results/`, somente estados, markers, manifests, commands, summaries já persistidos, provenance e evidência técnica pequena são selecionados.
- `dpca_metrics.jsonl`, `llm_decisions.jsonl`, `failed_llm_responses.jsonl`, logs científicos de servidor/processo e imagens são excluídos.
- O conteúdo staged deve passar por varredura de padrões conhecidos de credenciais antes do commit.
- Nenhum arquivo da origem pode ser alterado durante a exportação.

## Artefatos científicos relevantes omitidos

- `models/qwen2.5-7b-instruct-q4_k_m.gguf` — 4.683.073.536 bytes.
- `data/source_normal_holdout/TEP_FaultFree_Testing.RData` — 47.327.663 bytes.
- `data/source_normal_holdout/TEP_FaultFree_Testing.RData.zip` — 46.264.799 bytes.
- Partições CSV IDV(13), normal-reference e arquivos blind/normal-holdout — omitidos como payload de dataset.
- Métricas DPCA e decisões LLM por janela — omitidas como resultados científicos brutos; manifests, markers, statuses e summaries permanecem publicados.

