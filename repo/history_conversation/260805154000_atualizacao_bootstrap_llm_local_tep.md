---
schema_version: "1.0.0"
record_type: OPERATIONAL_CONVERSATION_SUMMARY
created_at: "2026-08-05T15:40:00-03:00"
filename_timestamp: "260805154000"
title: "Atualização do bootstrap da pesquisa sobre LLM local no TEP"
subject: "Consolidação operacional do escopo provisório, da tríade bibliográfica e da atualização do bootstrap canônico em pull request."
topics:
  - "Tennessee Eastman Process"
  - "IDV(13)"
  - "LLM local"
  - "DPCA"
  - "tríade bibliográfica"
  - "bootstrap"
  - "iniciação científica"
  - "não externalização de dados"
personas:
  conversation_owner: PSQZA
  formally_activated:
    - PSQZA
  mentioned_without_activation:
    - BANCA
routes: []
academic_status: PROVISIONAL
repository: prefix325/psqza-research
base_commits:
  psqza_research_main: "2d5f2207f6edf5baebe223e6542d36d356c70778"
  psqza_research_branch_before_summary: "bd14a612ee14b311bbf20304f620f8429ad431e4"
privacy:
  contains_sensitive_data: false
  private_reasoning_included: false
---

# Atualização do bootstrap da pesquisa sobre LLM local no TEP

## Estado da conversa

A conversa delimitou uma proposta de iniciação científica sobre a capacidade de uma LLM executada localmente para reconhecer e explicar a evolução temporal de uma falha industrial simulada no Tennessee Eastman Process. Todo o conteúdo permanece `PROVISIONAL`.

Não houve orientação formal da MECAI, opinião formal da BANCA, classificação formal de escrita pela VERSA, execução formal atribuída à TERRA_VERSA ou validação acadêmica independente. A BANCA foi mencionada apenas como fonte de objeções metodológicas prováveis.

## Tema preliminar consolidado

Avaliação de uma LLM local para identificação e explicação da evolução de uma falha gradual em séries temporais industriais, sob restrição verificável de não externalização dos dados, usando o Tennessee Eastman Process como ambiente público de estudo.

A falha `IDV(13)` permanece candidata provisória. A pesquisa não será apresentada como tentativa de substituir sistemas industriais maduros, sensores, métodos estatísticos especializados ou gêmeos digitais.

## Tríade bibliográfica de trabalho

Foi registrada como tríade preliminar:

1. Xing et al. (2024), *An Optimal Spatio-Temporal Hybrid Model Based on Wavelet Transform for Early Fault Detection*;
2. Khan et al. (2024), *FaultExplainer: Leveraging Large Language Models for Interpretable Fault Detection and Diagnosis*;
3. Kai et al. (2025), *Supervised deep learning algorithms for process fault detection and diagnosis under different temporal subsequence length of process data*.

A tríade organiza três dimensões do problema: detecção precoce e evolução lenta; uso de LLM para explicação no TEP; e controle do comprimento das subsequências temporais. Nenhum artigo foi promovido a evidência aceita. Identidade bibliográfica, texto integral, locadores e aderência específica à IDV(13) ainda precisam ser verificados.

## Correção metodológica central

A proposta não pode se limitar a trocar GPT-4o ou o1-preview por Llama, Qwen, Mistral ou outro modelo aberto. A mera substituição de modelo e infraestrutura seria uma contribuição científica fraca.

O objeto investigado passa a ser o conjunto de condições em que uma LLM local consegue observar, identificar, abster-se e explicar uma falha gradual. O caráter local é tratado como condição experimental mensurável: funcionamento offline, ausência de API externa, controle de versão e hash, monitoramento de tráfego de saída, latência, tokens, RAM e VRAM.

Como o TEP é público e simulado, o estudo poderá demonstrar um pipeline sem externalização de dados, mas não comprovará proteção de segredos industriais reais, segurança completa ou conformidade regulatória.

## Desenho experimental preliminar

O recorte recomendado contém:

- um ambiente: Tennessee Eastman Process;
- uma falha focal candidata: IDV(13);
- uma referência estatística: DPCA com T² e SPE/Q;
- uma LLM aberta executada integralmente em ambiente local;
- janelas temporais progressivas sem acesso a dados futuros;
- respostas estruturadas em `normal`, `anomalia` ou `evidência insuficiente`;
- avaliação de atraso de identificação, falsos alarmes, consistência, fidelidade explicativa e custo computacional.

A DPCA não é tratada como adversária que a LLM precisa superar. Ela serve como referência instrumental especializada para estabelecer o instante estatístico de detecção e as variáveis contribuintes.

Permanecem propostas três condições:

1. DPCA como referência numérica;
2. LLM local analisando uma representação temporal estruturada sem receber a saída da DPCA;
3. LLM local assistida por evidências da DPCA para avaliar interpretação.

A terceira condição ainda pode ser retirada do estudo inicial para evitar ampliação excessiva.

## Pergunta e hipótese provisórias

Pergunta de trabalho:

> Quais são os limites de uma LLM local para identificar e explicar a evolução temporal da falha IDV(13) no Tennessee Eastman Process, quando submetida a janelas progressivas e comparada a uma referência estatística por DPCA?

Hipótese de trabalho:

> A LLM local provavelmente não superará consistentemente a DPCA como detector numérico especializado, mas poderá reconhecer padrões graduais e produzir explicações úteis quando receber uma representação temporal adequada.

A hipótese admite resultado negativo e ainda não foi formalmente congelada.

## Contribuição metodológica pretendida

Para ultrapassar a mera troca de modelo, o estudo deverá produzir um protocolo reproduzível composto por:

- contrato estruturado de representação temporal;
- avaliação causal janela a janela;
- regra explícita de alarme, persistência e abstenção;
- separação entre atraso estatístico e latência computacional;
- avaliação de afirmações sustentadas e não sustentadas;
- evidência verificável de execução local;
- registro de modelo, quantização, prompt, parâmetros, hardware e hashes.

## Atualização canônica realizada

Foi criada a branch `update/bootstrap-local-llm-tep-20260805` a partir da `main` no commit `2d5f2207f6edf5baebe223e6542d36d356c70778`.

O bootstrap foi atualizado nos seguintes objetos:

- `project/current_state.md`;
- `project/research_graph.json`;
- `project/checkpoint.json`;
- `history_conversation/index.json`;
- sínteses operacionais em `history_conversation/`.

Foi aberto o pull request em rascunho `#5`, intitulado *Atualizar bootstrap da pesquisa sobre LLM local no TEP*. Antes desta síntese, a branch estava no commit `bd14a612ee14b311bbf20304f620f8429ad431e4`.

O pull request não promove qualquer conteúdo para `ACCEPTED` e não foi mesclado.

## Pendências

- confirmar ou rejeitar a IDV(13) como falha focal final;
- verificar integralmente a tríade e antecedentes diretos;
- construir uma matriz de lacuna e contribuição;
- congelar a linhagem do conjunto TEP, intervalo de amostragem e protocolo de execuções;
- selecionar LLM, quantização, hardware e stack de inferência local;
- congelar representação temporal, comprimentos de janela e defasagens da DPCA;
- definir alarmes, persistência, abstenção, métricas, limiares e critérios de sucesso;
- decidir se a condição DPCA assistindo a LLM integra a iniciação científica;
- obter avaliação acadêmica formal antes de aceitar pergunta, hipótese, método ou contribuição;
- executar validações do repositório e do CI;
- após eventual merge, testar a restauração do bootstrap em nova sessão.

## Próximo passo recomendado

Construir a matriz de lacuna e contribuição entre a tríade, antecedentes diretos e o protocolo proposto. Somente depois devem ser congeladas a pergunta de pesquisa, a hipótese e a configuração experimental.
