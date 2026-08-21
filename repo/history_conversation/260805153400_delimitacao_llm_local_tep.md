---
schema_version: "1.0.0"
record_type: OPERATIONAL_CONVERSATION_SUMMARY
created_at: "2026-08-05T15:34:00-03:00"
filename_timestamp: "260805153400"
title: "Delimitação da LLM local no TEP"
subject: "Refinamento do problema, da contribuição e do desenho experimental preliminar para uma LLM local aplicada à falha IDV(13)."
topics:
  - "Tennessee Eastman Process"
  - "IDV(13)"
  - "LLM local"
  - "DPCA"
  - "detecção precoce"
  - "explicabilidade"
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
  psqza-research: "2d5f2207f6edf5baebe223e6542d36d356c70778"
privacy:
  contains_sensitive_data: false
  private_reasoning_included: false
---

# Delimitação da LLM local no TEP

## Estado acadêmico

Todo o conteúdo desta síntese permanece `PROVISIONAL`. A conversa refinou o escopo e identificou objeções prováveis de banca, mas não registrou aceitação científica, opinião formal da BANCA, orientação formal da MECAI ou admissão formal de escrita pela VERSA.

## Tríade bibliográfica de trabalho

A tríade bibliográfica preliminar do projeto passa a ser tratada como:

1. Xing et al. (2024), *An Optimal Spatio-Temporal Hybrid Model Based on Wavelet Transform for Early Fault Detection* — base para detecção precoce, janelas temporais e evolução lenta de falhas.
2. Khan et al. (2024), *FaultExplainer: Leveraging Large Language Models for Interpretable Fault Detection and Diagnosis* — antecedente direto para uso de LLMs no TEP e para os riscos de dependência das evidências e alucinação.
3. Kai et al. (2025), *Supervised deep learning algorithms for process fault detection and diagnosis under different temporal subsequence length of process data* — base para controlar o comprimento das subsequências temporais.

Os três trabalhos ainda exigem verificação de texto integral, identidade bibliográfica, locadores e aderência específica à IDV(13) antes de sustentar alegações aceitas.

## Correção de posicionamento

A pesquisa não deve ser apresentada como simples substituição de GPT-4o ou o1-preview por Llama, Qwen, Mistral ou outro modelo aberto executado localmente. A mera troca de modelo e infraestrutura seria uma contribuição científica fraca e vulnerável à objeção de banca.

O caráter local deve ser tratado como condição experimental mensurável: inferência sem API externa, ausência de externalização dos dados, funcionamento offline, controle de versão e hash, latência, memória, VRAM, tokens e tráfego de saída. O uso do TEP, por ser público e simulado, permite demonstrar a arquitetura de não externalização, mas não comprova proteção de segredos industriais reais ou conformidade completa.

## Problema de pesquisa preliminar

Investigar os limites e as condições de viabilidade de uma LLM local para reconhecer e explicar a evolução temporal de uma falha industrial gradual, sob restrição verificável de não externalização dos dados.

## Pergunta preliminar

Quais são os limites de uma LLM local para identificar e explicar a evolução temporal da falha IDV(13) no Tennessee Eastman Process, quando submetida a janelas progressivas e comparada a uma referência estatística por DPCA?

## Desenho experimental preliminar

O escopo recomendado para iniciação científica é restrito a:

- ambiente: Tennessee Eastman Process;
- falha focal candidata: IDV(13);
- referência instrumental: DPCA com estatísticas T² e SPE/Q;
- objeto investigado: uma LLM aberta executada integralmente em ambiente local;
- protocolo: janelas temporais progressivas sem acesso a observações futuras;
- saída obrigatória: normal, anomalia ou evidência insuficiente, acompanhada de justificativa rastreável;
- métricas: atraso de identificação, falsos alarmes, consistência, fidelidade das explicações, latência e uso de recursos.

A DPCA não deve ser apresentada como adversária que a LLM precisa superar. Ela funciona como referência especializada para estabelecer o instante estatístico de detecção e as variáveis contribuintes.

Três condições permanecem propostas para avaliação posterior:

1. DPCA como referência numérica;
2. LLM local analisando representação temporal estruturada sem receber a saída da DPCA;
3. LLM local assistida pelas evidências da DPCA para avaliar interpretação.

A inclusão da terceira condição no primeiro estudo ainda precisa ser decidida para evitar ampliação excessiva.

## Contribuição metodológica esperada

Para não reduzir o estudo a uma troca de modelo, o trabalho deverá produzir um protocolo reproduzível composto por:

- contrato estruturado para representar janelas temporais;
- avaliação causal janela a janela;
- regra explícita de alarme e abstenção;
- separação entre atraso estatístico e latência computacional;
- avaliação de afirmações sustentadas e não sustentadas;
- evidência verificável de execução local sem chamadas externas;
- registro de modelo, quantização, prompt, parâmetros, hardware e hashes.

## Hipótese preliminar

A LLM local provavelmente não superará de forma consistente a DPCA como detector numérico especializado, mas poderá reconhecer padrões graduais e produzir explicações úteis quando receber uma representação temporal adequada. A hipótese permanece aberta a resultado negativo.

## Decisões ainda abertas

- confirmar a IDV(13) como falha focal final;
- selecionar a versão e a linhagem exata do conjunto TEP;
- escolher a LLM local, quantização e ambiente de execução;
- congelar a representação temporal estruturada;
- definir comprimentos de janela e defasagens da DPCA;
- definir regra de alarme, persistência e abstenção;
- decidir se a condição DPCA → LLM integra a iniciação científica ou fica como extensão;
- formalizar métricas, limiares, hipóteses e critérios de sucesso;
- verificar integralmente a tríade bibliográfica e antecedentes diretos como FD-LLM e LLM-TSFD.

## Próximo passo recomendado

Produzir uma matriz de lacuna e contribuição comparando a tríade e os antecedentes diretos com o protocolo proposto, antes de congelar pergunta, hipótese e experimento.
