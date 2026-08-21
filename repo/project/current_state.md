# PSQZA Current Academic State

Status: `PROVISIONAL`.

## Execução formal e emenda operacional pós-freeze

- TARGET simulationRuns 1–57 estão `COMPLETE` e são imutáveis.
- TARGET simulationRun 58 tem DPCA `COMPLETE`, LLM `FAILED` e lote `FAILED`.
- A LLM attempt 0001 da run 58 permanece preservada. A causa raiz comprovada é truncamento da saída no teto formal de 768 tokens (`finish_reason=length`), sem looping ou degeneração.
- `POST_FREEZE_OPERATIONAL_AMENDMENT_001` altera prospectivamente apenas o teto de geração da LLM de 768 para 1024. A lógica metodológica não muda; a alteração não foi informada por detection rate, delay, H1/H2/H3 ou desempenho da IDV(13).
- Nenhuma retomada científica está autorizada antes da aceitação técnica sintética e da revalidação dos gates.
- A aceitação técnica lançada em 2026-08-16 encerrou antes da inferência (`inference_count=0`): havia 1259 MiB de VRAM livre e o runtime registrou offload de 0/29 camadas, corretamente recusado pelo gate GPU fail-closed. O gate real permanece bloqueado e nenhuma `attempt_0002` foi criada.
- Após novo precheck com 7297 MiB livres, a única inferência sintética ainda pendente passou: 29/29 camadas em GPU, parser JSON `PASS`, 567 completion tokens e `finish_reason=stop`. O gate técnico foi reconciliado para `REAL START READY`; a retomada científica continua separada e nenhuma `attempt_0002` foi criada.

## Delimitação vigente

- O Tennessee Eastman Process é o ambiente público e simulado inicial de estudo.
- A IDV(13) permanece como falha focal de trabalho, ainda sujeita à validação final após a matriz de lacuna e contribuição.
- O objeto científico é a capacidade de uma LLM de propósito geral de detectar o surgimento de uma condição anormal em um sistema industrial multivariado em regime zero-shot quanto à falha.
- Zero-shot é definido em relação à falha: a LLM pode conhecer a estrutura do processo, o significado dos sensores e a operação normal, mas não recebe treinamento específico para falhas, exemplos rotulados de IDV(13), descrição da IDV(13), flags ocultas do simulador ou saída da DPCA na condição primária.
- Detectar anormalidade é o objetivo primário. Identificar nominalmente a IDV(13) é uma tarefa secundária e não é necessária para validar a capacidade de detecção.
- A execução local é uma condição experimental mensurável, não uma alegação suficiente de novidade: ausência de API externa, funcionamento offline, controle de versão e hash, tráfego de saída, latência, RAM, VRAM e tokens devem ser registrados.
- Como o TEP é público e simulado, o estudo poderá demonstrar arquitetura sem externalização, mas não provar proteção de segredos industriais reais ou conformidade completa.

## Tríade bibliográfica preliminar

1. Xing et al. (2024), *An Optimal Spatio-Temporal Hybrid Model Based on Wavelet Transform for Early Fault Detection*.
2. Khan et al. (2024), *FaultExplainer: Leveraging Large Language Models for Interpretable Fault Detection and Diagnosis*.
3. Kai et al. (2025), *Supervised deep learning algorithms for process fault detection and diagnosis under different temporal subsequence length of process data*.

A tríade permanece como base de trabalho. Texto integral, identidade bibliográfica, locadores, aderência à IDV(13) e capacidade de sustentar alegações ainda precisam ser verificados. Khan et al. deve ser tratado como antecedente direto. A matriz de lacuna deve incluir também antecedentes de detecção zero-shot e normal-only com LLMs antes de qualquer alegação de novidade.

## Pergunta preliminar

Uma LLM de propósito geral, sem treinamento específico para falhas e contextualizada apenas pelo conhecimento do processo e de sua operação normal, é capaz de detectar em regime zero-shot o surgimento de uma condição anormal em um sistema industrial multivariado?

O Tennessee Eastman Process com a IDV(13) é o caso experimental focal para responder essa pergunta em progressão temporal causal.

## Hipóteses preliminares

### H1 — Capacidade de detecção zero-shot

Uma LLM de propósito geral, contextualizada apenas com o conhecimento do processo e da operação normal, é capaz de detectar uma condição anormal provocada por uma falha não apresentada previamente, sem treinamento específico para essa falha.

### H2 — Acúmulo temporal de evidência

A capacidade de detecção da LLM aumenta à medida que evidências multivariadas da falha se acumulam ao longo de janelas temporais causais, produzindo uma transição observável de `NORMAL` ou `EVIDÊNCIA_INSUFICIENTE` para `ANOMALIA` após o início real da perturbação.

### H3 — Coerência multivariada da decisão

Quando a LLM indica anomalia, as variáveis e tendências utilizadas em sua justificativa apresentam correspondência verificável com as alterações efetivamente observadas no sistema, mesmo sem a LLM conhecer previamente a identidade da IDV(13).

Resultados negativos para H1, H2 ou H3 permanecem cientificamente admissíveis.

## Desenho experimental preliminar

- Ground truth experimental: instante de ativação da IDV(13) controlado pelo simulador.
- Referência estatística independente: DPCA com T2 e SPE/Q.
- Modelo investigado: uma LLM aberta de propósito geral executada integralmente em ambiente local.
- Condição primária: LLM fault-blind, com conhecimento do processo e referência de operação normal, sem receber saída da DPCA.
- Protocolo: janelas temporais progressivas e causais, sem acesso a observações futuras.
- Saída da LLM: `NORMAL`, `EVIDÊNCIA_INSUFICIENTE` ou `ANOMALIA`, acompanhada de evidências e justificativa rastreável.
- Métricas: atraso de detecção a partir do início real da falha, falsos alarmes, consistência, coerência/fidelidade das evidências, latência de inferência e uso de recursos.
- A DPCA não é ground truth nem professora da LLM; funciona como referência estatística independente para comparação temporal e diagnóstico quantitativo.

Uma condição secundária em que a LLM recebe evidências da DPCA permanece proposta, mas sua inclusão no estudo inicial ainda deve ser decidida.

## Contribuição metodológica necessária

Para evitar uma mera troca de modelo, o estudo deverá produzir um protocolo reproduzível com:

- referência explícita de operação normal;
- contrato estruturado de representação temporal multivariada;
- avaliação causal janela a janela;
- regra explícita de alarme, persistência e abstenção;
- separação entre atraso de detecção e latência computacional;
- avaliação de coerência entre justificativas da LLM e alterações observáveis no processo;
- evidência de execução local sem chamadas externas;
- registro de modelo, quantização, prompt, parâmetros, hardware e hashes.

## Estado dos entregáveis

O artigo é o foco científico inicial. O pré-projeto é o caminho crítico de admissão. A dissertação integra progressivamente trabalho aceito. A agenda de doutorado (`doctoral agenda`) permanece um entregável integrado e não constitui tese. Nenhum item acima é cientificamente aceito apenas por estar versionado no repositório.
