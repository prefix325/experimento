# Espelho leve do ambiente local TEP/LLM/DPCA

Este repositório público é uma cópia operacional, seletiva e versionada de `X:\PSQZA_TEP_LOCAL`. Ele existe para auditoria, continuidade do trabalho no ambiente MECAI/VERAS e preservação da estrutura lógica do experimento sem publicar artefatos pesados ou dados sensíveis.

Este repositório **não é** o estado científico canônico `psqza-research`. O estado canônico continua identificado pelos commits, freezes, manifests e hashes registrados em `repo/`. A origem local não foi movida, limpa ou modificada para produzir este espelho.

## Estado congelado representado

- Campanha formal: 1.000/1.000 lotes concluídos.
- Method freeze: `TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH`.
- Commit do `FINAL_CAMPAIGN_MANIFEST`: `3083558c1aac86508ed7e4fbc9f9b2b33696e701`.
- SHA-256 do manifesto: `d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5`.
- O plano estatístico prospectivo está em `repo/project/final_campaign/STATISTICAL_ANALYSIS_PLAN.md`.

## Conteúdo

- `repo/`: código, documentação, schemas, testes, governança e artefatos científicos versionados, preservando o prefixo da origem; o `.git` interno foi deliberadamente excluído.
- `manifests/`: manifests operacionais e registros de preparação leves.
- `results/`: somente estados, markers `COMPLETE`, manifests, comandos, provenance, resumos persistidos e aceitação/observabilidade técnica leve.
- `data/`: apenas README, manifests e checksums; nenhum dataset bruto.
- `models/`: licença e documentação; nenhum peso de modelo.
- `logs/`: pequenos logs de preparação úteis à auditoria.
- `EXPORT_INVENTORY.md` e `EXPORT_INVENTORY.json`: inventário reproduzível da seleção e das exclusões.

## Exclusões deliberadas

Não são publicados pesos GGUF/safetensors, datasets CSV/RData/archives, imagens ou volumes Docker, caches, ambientes virtuais, metadados Git aninhados, outputs científicos por janela (`dpca_metrics.jsonl`, `llm_decisions.jsonl`), logs científicos volumosos, credenciais ou arquivos acima de 20 MiB.

Os artefatos omitidos continuam vinculados por manifests, seleção formal, provenance e hashes quando disponíveis. Reproduções futuras devem obter os dados e o modelo por canais autorizados e verificar os hashes antes de executar qualquer pipeline.

## Segurança e integridade

O conteúdo publicado passa por auditorias locais de tamanho, extensões pesadas, metadados Git aninhados e padrões conhecidos de segredo antes do commit. Nenhuma análise, DPCA ou inferência LLM é executada durante a criação deste espelho.

