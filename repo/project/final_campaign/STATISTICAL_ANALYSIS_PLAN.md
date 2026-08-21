# Statistical Analysis Plan — campanha formal TEP/LLM/DPCA

## Status e proveniência

- Tipo: plano estatístico prospectivo, anterior à inspeção dos resultados agregados.
- Corpus: campanha formal concluída, auditada e congelada.
- `FINAL_CAMPAIGN_MANIFEST` commit local declarado: `3083558c1aac86508ed7e4fbc9f9b2b33696e701`.
- `FINAL_CAMPAIGN_MANIFEST` SHA-256: `d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5`.
- Method freeze: `TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH`.
- Nível nominal dos intervalos: 95%, bilateral.
- Este plano não contém estimativas, contagens de eventos, taxas, delays observados, testes ou conclusões da campanha.

H1, H2 e H3 são preservadas como **hipóteses/eixos de avaliação pré-especificados**, e não como hipóteses nulas estatísticas clássicas criadas retrospectivamente. Resultados futuros serão apresentados como estimativas, incerteza, testes quando previstos e evidência por eixo; não haverá linguagem de “aceitar H1” ou “rejeitar H1” apenas com base em p-value.

O objetivo é fixar estimandos, denominadores, regras de inclusão, métodos de incerteza e outputs antes da agregação. Contratos congelados e regras nativas dos detectores prevalecem sobre este documento. Nenhum threshold científico será criado ou redefinido durante a análise.

### Fontes técnicas vinculadas para fechamento prospectivo deste SAP

Espelho técnico somente leitura: `prefix325/experimento@936ff98d67e783ae21f36204db7d448c660c7b72`.

Esse repositório é fonte técnica leve e **não substitui** o estado científico canônico em `psqza-research`. Para as definições abaixo foram vinculados, sem inspeção de resultados agregados:

- `repo/experiments/tep/local_llm/config/evaluation_contract.json` — blob Git `183297c3570c6a6b2ceab3c9838ae3ec4ca3cd0e`;
- `repo/experiments/tep/local_llm/config/formal_run_selection.json` — blob Git `09b164f567b504b57e070f416910bd13d77dda7c`;
- `repo/experiments/tep/local_llm/config/formal_normal_holdout_selection.json` — blob Git `8fddb354a7c8853a8760b41a1012b4c16e85d930`;
- `repo/experiments/tep/local_llm/config/h3_evidence_reference.json` — blob Git `fbda319ba744054d33af2bf4f2cd99d264a100fc`;
- `repo/experiments/tep/local_llm/src/tep_local/dpca.py` — blob Git `668255aff7819032dd3aeb204e24cb2cca213b91`;
- `repo/experiments/tep/local_llm/src/tep_local/evaluation.py` — blob Git `7b992d573dfc34d09d9811bb04db66ce064520c5`.

## 1. Unidade inferencial

A unidade inferencial primária é a `simulationRun`.

Janelas dentro de uma run são observações temporais dependentes da mesma trajetória. Elas não serão tratadas como réplicas independentes, não aumentarão artificialmente o tamanho amostral e não serão reamostradas isoladamente. `FIRST_INDICATION`, `CONFIRMED_DETECTION`, alarmes DPCA brutos e confirmações DPCA pertencem à trajetória que os originou.

Quando evidências ou janelas forem resumidas, sua estrutura será preservada como:

```text
evidence item ⊂ window ⊂ simulationRun
```

Bootstrap, intervalos e comparações que utilizem reamostragem operarão no nível da run. Na comparação pareada, o par LLM–DPCA da mesma `simulationRun` será reamostrado como um único cluster.

## 2. Populações, estimandos e conjuntos de análise

### 2.1 LLM formal — TARGET

- Universo formal elegível: `simulationRun 11..500`, total 490, com runs `1..10` excluídas previamente por desenvolvimento/piloto.
- Amostra: 50 runs selecionadas sem reposição por `formal_run_selection.json`, seed 42.
- Nenhuma exclusão posterior será baseada no resultado.

Estimando primário: probabilidade, no regime formal de trajetórias TEP elegíveis definido acima, de uma run apresentar o endpoint binário especificado pelo protocolo. Os intervalos de incerteza da amostra de 50 runs são interpretados como incerteza de estimação sob esse regime formal, e não como evidência de generalização para processo industrial real ou para as runs de desenvolvimento excluídas.

### 2.2 LLM formal — NORMAL HOLDOUT

- Universo formal: FaultFree Testing `simulationRun 1..500`.
- Amostra: 50 runs selecionadas sem reposição por `formal_normal_holdout_selection.json`, seed 43.
- Cada run é completamente fault-free no uso deste estudo.

Estimando primário: probabilidade, no regime formal de trajetórias FaultFree Testing, de uma run apresentar pelo menos um falso alarme no horizonte completo segundo o endpoint definido.

### 2.3 DPCA formal

- TARGET: 500 runs.
- NORMAL HOLDOUT: 500 runs.
- Total DPCA ampliado: 1.000 runs.

A análise ampliada DPCA descreve a incidência no corpus formal completo disponível. Quando intervalos forem apresentados para a DPCA ampliada, eles serão identificados como extrapolação model-based para trajetórias análogas do mesmo regime TEP, e não como incerteza sobre a própria contagem já observada nas 500 runs do corpus.

### 2.4 Comparação principal LLM × DPCA

A comparação principal será pareada por `simulationRun` no subconjunto comum:

- TARGET: as mesmas 50 runs selecionadas para a LLM;
- NORMAL HOLDOUT: as mesmas 50 runs selecionadas para a LLM.

O estimando comparativo primário é a diferença pareada de proporções entre os sistemas sobre as mesmas trajetórias. O pareamento não poderá ser substituído por comparação entre amostras independentes.

### 2.5 DPCA ampliada

As 500 TARGET e 500 NORMAL HOLDOUT da DPCA serão usadas como contexto e estimativa ampliada da referência estatística DPCA. Essa análise não substituirá a comparação pareada principal e não será apresentada como se tivesse o mesmo desenho da avaliação LLM com 50 runs por coorte.

### 2.6 Regra geral de inclusão

Será usada a attempt científica final referenciada pelo `COMPLETE.json` e pelo `FINAL_CAMPAIGN_MANIFEST`. Attempts históricas `FAILED`, `FAILED_TO_START`, `ABORTED` ou `PARTIAL` serão mantidas apenas como provenance operacional. Nenhum artefato parcial será combinado com a attempt final.

## 3. Definições operacionais dos endpoints

As regras de confirmação permanecem as regras nativas congeladas de cada sistema.

### 3.1 LLM

- Indicação bruta: existência de `FIRST_INDICATION` persistida na run.
- Detecção confirmada: existência de `CONFIRMED_DETECTION` persistida segundo `FIRST_INDICATION_CONCURRENT_FULL_SAMPLE_REFRESH_V1`.
- Sem confirmação: ausência de `CONFIRMED_DETECTION` ao término da trajetória.
- Em NORMAL HOLDOUT, os mesmos estados serão descritos como indicação bruta de falso alarme e falso alarme confirmado.

### 3.2 DPCA

- Indicação bruta: primeiro `alarm_raw=true` elegível segundo o contrato congelado.
- Detecção confirmada: primeiro ponto em que a persistência nativa de três amostras consecutivas é satisfeita.
- Sem confirmação: ausência de alarme persistente até o término da trajetória.
- Em NORMAL HOLDOUT, os endpoints serão denominados indicação bruta de falso alarme e falso alarme confirmado.

A coordenada temporal científica persistida da DPCA é o campo `sample` do registro `dpca_metrics.jsonl`. O código congelado escreve `sample`, `alarm_raw` e `alarm_persistent` em cada observação DPCA. Para métricas pós-onset, a persistência é resetada em `sample=161` conforme o contrato de avaliação.

Não será criada equivalência semântica entre a lógica interna dos dois detectores. A comparação será entre endpoints de função correspondente — bruto e confirmado — preservando as regras nativas.

## 4. H1 — detecção e falso alarme

H1 será tratada por estimação descritivo-inferencial. Não haverá threshold retrospectivo para declarar a hipótese/eixo “aceito” ou “rejeitado”.

### 4.1 TARGET pós-onset

Para cada detector e conjunto de análise serão reportados:

1. proporção de runs com indicação bruta pós-onset;
2. proporção de runs com detecção confirmada pós-onset;
3. proporção de runs sem confirmação.

O denominador principal LLM e da comparação pareada DPCA será sempre 50, inclusive quando não houver evento. Na análise DPCA ampliada, o denominador TARGET será 500.

Endpoint primário TARGET: detecção confirmada por run. Indicação bruta e ausência de confirmação serão endpoints secundários predefinidos.

### 4.2 NORMAL HOLDOUT

Para cada detector serão reportados:

1. proporção de runs com indicação bruta de falso alarme;
2. proporção de runs com falso alarme confirmado;
3. proporção sem falso alarme confirmado.

O endpoint principal é explicitamente a **proporção/risco de trajetórias com pelo menos um falso alarme no horizonte completo da `simulationRun`**. Não é uma taxa por janela, por amostra ou por oportunidade de decisão.

O denominador principal LLM e pareado DPCA será 50. Na análise DPCA ampliada, o denominador NORMAL HOLDOUT será 500.

Endpoint primário NORMAL HOLDOUT: falso alarme confirmado por run. Indicação bruta será endpoint secundário.

Métricas por oportunidade, quando já previstas pelo contrato operacional, poderão ser exibidas apenas como descrição secundária e nunca como substitutas do estimando por run ou como `n` inferencial independente.

### 4.3 TARGET pré-onset — análise secundária predefinida

O trecho `samples 1..160` da TARGET será auditado separadamente para falso alarme.

Por `simulationRun`, serão definidos:

- LLM raw pre-onset: pelo menos uma decisão `ANOMALY` com `sample_end <= 160`;
- LLM confirmed pre-onset: candidato e sua própria janela de verificação `k+4` ambos com endpoint `<=160` e ambos `ANOMALY`;
- DPCA raw pre-onset: pelo menos um `alarm_raw=true` com `sample <=160`;
- DPCA confirmed pre-onset: três excedências consecutivas inteiramente pré-onset, com confirmação `<=160`.

Candidatos LLM e persistência DPCA pré-onset são resetados no onset; nenhum estado pré-onset pode confirmar um evento pós-onset.

Denominadores: LLM TARGET 50; DPCA pareada 50; DPCA ampliada 500. Esta análise não será misturada nem pooled com NORMAL HOLDOUT.

### 4.4 Forma de apresentação

Cada proporção será apresentada como `eventos / runs elegíveis`, estimativa pontual e intervalo de 95%. A ausência de evento não será removida do denominador.

## 5. H2 — tempo até indicação e confirmação

H2 aplica-se às runs TARGET.

### 5.1 Coordenada temporal LLM

Para a LLM, o instante causal é o endpoint da janela persistida:

```text
LLM_delay_minutes = (sample_end - 161) * 3
```

Serão calculados separadamente:

- delay até `FIRST_INDICATION`;
- delay até `CONFIRMED_DETECTION`.

### 5.2 Coordenada temporal DPCA

Para a DPCA, o instante de decisão é o campo persistido `sample`:

```text
DPCA_raw_delay_minutes = (first_post_onset_alarm_raw_sample - 161) * 3
DPCA_confirmed_delay_minutes = (first_post_onset_persistent_alarm_sample - 161) * 3
```

`first_post_onset_persistent_alarm_sample` é a amostra em que a terceira excedência consecutiva pós-reset satisfaz a persistência nativa. O estado de persistência usado para a métrica pós-onset é reiniciado em `sample=161`.

### 5.3 Runs sem evento

Para uma run sem o evento correspondente:

- `detected = false`;
- `delay_minutes = null`;
- a run permanece no denominador de detecção;
- a run não entra silenciosamente no denominador do resumo condicional de delay.

Valores negativos, índices impossíveis ou inconsistentes com o contrato serão tratados como falha de integridade, não truncados para zero.

### 5.4 Resumos predefinidos e casos degenerados

Entre runs com delay definido serão apresentados, sempre com o denominador condicional explícito:

- mediana;
- primeiro e terceiro quartis e IQR;
- média;
- desvio-padrão;
- mínimo e máximo;
- intervalo de 95% da mediana e da média por bootstrap no nível da run.

Regras prospectivas para denominadores condicionais:

- `n=0`: sem estimativa de delay e sem IC; reportar `NA/undefined` e o motivo;
- `n=1`: reportar o único valor observado e o denominador; não produzir DP, IQR ou IC inferencial como se houvesse amostra múltipla;
- `n>=2`: aplicar os resumos e métodos predefinidos quando matematicamente válidos;
- BCa indefinido: usar intervalo percentil de 95% e registrar a razão;
- se o método alternativo também for matematicamente indefinido: reportar `NA/undefined` com motivo, sem escolher outro método após ver os resultados.

Mediana/IQR e média/desvio-padrão serão reportados conjuntamente; nenhum deles será escolhido ou omitido depois da inspeção da distribuição. Mínimo e máximo não receberão interpretação inferencial.

O delay confirmado é um endpoint do sistema detector + regra de confirmação. Diferenças nele não serão atribuídas exclusivamente ao detector bruto quando as regras de pós-processamento diferirem.

## 6. NORMAL HOLDOUT

Cada trajetória NORMAL HOLDOUT corresponde ao horizonte completo de 960 amostras. Para a LLM são programadas 189 janelas e não há early-stop.

Serão mantidos separadamente:

- qualquer indicação bruta de anomalia;
- falso alarme confirmado pela regra nativa.

Não será calculado delay relativo a fault onset em NORMAL HOLDOUT, pois não existe onset de falha. Tempo ou janela do primeiro falso alarme poderá ser exibido apenas como localização temporal descritiva da run, com denominador explícito, e não como delay de detecção.

O número total de janelas ou oportunidades não será usado como `n` inferencial independente.

## 7. Comparação LLM × DPCA

### 7.1 Endpoints binários pareados

Para cada coorte e endpoint funcionalmente correspondente, será construída uma tabela por run:

| LLM | DPCA | Interpretação |
|---|---|---|
| 0 | 0 | concordância negativa |
| 0 | 1 | discordância DPCA-only |
| 1 | 0 | discordância LLM-only |
| 1 | 1 | concordância positiva |

Serão reportados os quatro números, concordância total, duas discordâncias e diferença pareada de proporções, sempre com 50 pares como denominador principal.

Se for produzido teste inferencial para o endpoint binário, será usado o teste exato bilateral de McNemar, baseado somente nos pares discordantes. Não será usada aproximação qui-quadrado quando a quantidade de discordâncias for pequena. Se não houver pares discordantes, o resultado será registrado diretamente, sem forçar uma aproximação assintótica.

A diferença pareada de proporções receberá intervalo de 95% obtido por reamostragem pareada no nível da `simulationRun`. O teste não converterá a análise em decisão binária de hipótese/eixo “aceito”.

### 7.2 Delays pareados

Delays só serão comparados diretamente nas runs em que o mesmo endpoint esteja definido para ambos os detectores. Serão reportados:

- número total de pares elegíveis original;
- número em que nenhum, somente um ou ambos detectaram;
- número de pares com delay definido em ambos;
- diferença pareada `LLM - DPCA` em minutos;
- mediana, IQR, média, desvio-padrão, mínimo/máximo e intervalos por bootstrap pareado quando definidos.

Essa análise será explicitamente denominada condicional a ambos os eventos terem ocorrido. Ela não substituirá a análise binária de detecção e não será generalizada às runs sem detecção.

Não será criada imputação punitiva de delay para não detecções.

Se um teste de localização pareado for apresentado como análise secundária, será usado teste exato bilateral de sinais. Diferenças exatamente zero serão classificadas como empates, reportadas separadamente e excluídas do denominador binomial do teste; o teste usará somente o número de diferenças positivas e negativas não nulas, com probabilidade nula `p=0,5`.

### 7.3 Detector bruto versus sistema confirmado

Resultados serão separados em:

- resposta bruta do detector;
- resposta do sistema operacional completo, após a regra nativa de confirmação.

Concordância em um nível não será usada para inferir concordância no outro.

## 8. Incerteza

### 8.1 Proporções

Intervalos primários de 95% para detection, false alarm e no-detection rates na amostra LLM e no subconjunto pareado usarão o intervalo de Wilson. A aproximação normal ingênua `p ± 1,96 × SE` não será o método primário.

Quando a contagem estiver no limite zero ou no denominador total, o intervalo exato de Clopper–Pearson poderá ser apresentado como análise de sensibilidade, identificado como conservador e sem substituir Wilson.

Para a DPCA ampliada, a proporção observada nas 500 runs será apresentada primeiro como descrição do corpus completo. Qualquer IC adicional será explicitamente rotulado como inferência model-based para trajetórias análogas do mesmo regime TEP.

### 8.2 Bootstrap

- Número predefinido de réplicas: 10.000.
- Seed predefinido: `20260820`.
- Intervalo preferencial: BCa de 95%; se BCa for matematicamente indefinido, usar percentil de 95% e registrar a razão.
- Unidade de reamostragem: `simulationRun`.
- Comparações: reamostragem do par LLM–DPCA como cluster indivisível.
- H3: reamostragem de runs inteiras, preservando janelas e evidence items dentro da run.

Nenhum bootstrap será realizado por janela independente.

## 9. H3 — process-evidence groundedness

H3 seguirá exclusivamente o contrato congelado `evaluation_contract.json` e a referência `h3_evidence_reference.json`. Não serão criados novos limiares a partir dos resultados.

Escopo primário H3: as 50 runs TARGET avaliadas pela LLM. Uma eventual auditoria H3 do NORMAL HOLDOUT não pertence ao endpoint primário e, se realizada, deverá ser rotulada como secundária/exploratória antes de interpretação.

### 9.1 Unidade e elegibilidade

Cada `evidence item` persistido possui `variable`, `claim` e `observation`.

- `variable_valid = true` quando `evidence.variable` corresponde exatamente a uma das 52 variáveis permitidas, está presente no payload numérico da mesma janela e possui thresholds na referência H3;
- `claim_valid = true` quando `claim` pertence ao enum congelado: `HIGH`, `LOW`, `INCREASE`, `REDUCTION`, `VARIABILITY`;
- item numericamente verificável = `variable_valid AND claim_valid`.

`observation` é material de auditoria humana/qualitativa e não determina o score H3 primário.

### 9.2 Regras numéricas congeladas

- `HIGH`: `max_z >= high_max_z_q99`;
- `LOW`: `min_z <= low_min_z_q01`;
- `INCREASE`: `slope_z_per_sample >= increase_slope_q99 AND end_z > start_z`;
- `REDUCTION`: `slope_z_per_sample <= reduction_slope_q01 AND end_z < start_z`;
- `VARIABILITY`: `round(max_z - min_z, 4) >= high_variability_range_q99`.

### 9.3 Numeradores, denominadores e agregação

- `evidence_item_score = 1` quando a correspondência da variável é válida e o claim estruturado passa sua regra numérica; caso contrário, `0`;
- `coverage = número de evidence items numericamente verificáveis / número total de evidence items`;
- `response_score = média dos evidence_item_score` da resposta;
- se uma resposta `ANOMALY` não contiver evidence, `response_score = 0`;
- se `NORMAL` ou `EVIDENCE_INSUFFICIENT` não contiver evidence, a resposta é `not applicable` para o score H3;
- `run_score = média dos response_score aplicáveis dentro da simulationRun`;
- run sem qualquer `response_score` aplicável recebe `run_score = null` e não é imputada;
- estatística macro primária H3 = média dos `run_score` aplicáveis, dando peso igual a cada run aplicável;
- distribuição dos `run_score`, número de runs aplicáveis e coverage serão sempre reportados separadamente.

Um agregado micro por evidence item poderá ser apresentado apenas como secundário e com denominador explícito; não substituirá a agregação macro por run.

Claims narrativos de processo não capturados pelo enum estruturado, inclusive alegações causais ou observações não suportadas pelo payload, poderão ser auditados qualitativamente como `unsupported process claims`, mas não serão incorporados retroativamente ao score H3 primário nem receberão novo threshold quantitativo.

### 9.4 Casos degenerados H3

- zero evidence items globais: `coverage = null`, com contagem zero explícita;
- run sem resposta aplicável: `run_score = null` e razão registrada;
- zero runs aplicáveis: macro H3 `NA/undefined`, sem IC;
- uma run aplicável: reportar o valor individual e o denominador, sem DP/IC inferencial;
- duas ou mais runs aplicáveis: aplicar resumos/bootstrap quando matematicamente válidos;
- BCa indefinido: fallback percentil; se ainda indefinido, `NA/undefined` com motivo.

Evidence items, janelas e claims não serão tratados como observações inferenciais independentes.

## 10. Multiplicidade e classificação das análises

### 10.1 Primárias

- TARGET: detecção confirmada por run, por detector e diferença pareada LLM–DPCA;
- NORMAL HOLDOUT: falso alarme confirmado por run, por detector e diferença pareada;
- TARGET H2: estimação condicional predefinida do delay confirmado, sem decisão binária de hipótese;
- H3: macro `run_score` conforme contrato congelado, acompanhado de coverage e denominadores.

### 10.2 Secundárias

- indicações brutas;
- delays até primeira indicação;
- falso alarme TARGET pré-onset;
- concordância e discordâncias adicionais;
- teste exato de sinais para delays pareados, quando aplicável;
- DPCA ampliada em 500 + 500 runs;
- métricas por oportunidade já existentes no contrato, claramente separadas da unidade inferencial por run;
- análise de sensibilidade de provenance da emenda 768→1024.

### 10.3 Exploratórias

Qualquer estratificação, diagnóstico de distribuição ou visualização não listada neste plano será marcada como exploratória. Análises exploratórias não serão promovidas a confirmatórias.

O plano não estabelece thresholds para “aceitar” H1, H2 ou H3. Se p-values forem reportados para os dois contrastes binários primários — detecção confirmada TARGET e falso alarme confirmado NORMAL HOLDOUT — eles formarão uma única família e serão ajustados pelo método de Holm. P-values secundários ou exploratórios, se excepcionalmente produzidos, serão separados por família, ajustados por Holm e claramente rotulados; não serão misturados com a família primária.

Intervalos descritivos serão apresentados com transparência sobre multiplicidade e não reinterpretados como testes independentes não ajustados.

## 11. Dados ausentes e runs sem evento

- `no detection`: resultado binário válido, não dado ausente;
- ausência de `FIRST_INDICATION`: indicação bruta `false`; delay correspondente `null`;
- ausência de confirmation: confirmação `false`; delay confirmado `null`;
- run com indicação mas sem confirmação: permanece no denominador de indicação e de confirmação, com confirmação `false`;
- delay `null`: não será convertido em zero, máximo, infinito ou valor arbitrário;
- H3 sem denominador aplicável: métrica `null`, com motivo e contagem explícitos;
- arquivo ou campo obrigatório ausente contra o manifest: falha de integridade; a análise deve parar em vez de imputar;
- nenhuma exclusão ou imputação será determinada depois da observação do efeito sobre os resultados.

Os denominadores totais e condicionais serão apresentados lado a lado para impedir exclusão silenciosa de não detecções.

## 12. Emenda operacional 768 → 1024

A análise preservará integralmente a provenance da `POST_FREEZE_OPERATIONAL_AMENDMENT_001`.

- Runs LLM TARGET sob configuração base preservada: 14, 23, 24, 26, 27 e 55.
- Attempt pré-emenda relevante: TARGET run58, outer `attempt_0001` / LLM checkpoint `0001`, histórica e não final.
- Início da configuração efetiva: TARGET run58, outer `attempt_0002` / LLM checkpoint `0002`, reiniciada em window 0.
- Runs anteriores não serão excluídas, refeitas ou reinterpretadas.
- Resultados base não serão tratados como se tivessem usado o teto 1024.

Uma análise de sensibilidade de provenance, se realizada, será secundária e estritamente operacional/descritiva. Ela poderá verificar compatibilidade de completude de serialização e distribuição de comprimentos persistidos entre fases, mas:

- não avaliará eficácia de detecção por subgrupo como hipótese confirmatória;
- não será usada para tuning;
- não excluirá runs anteriores;
- reconhecerá o forte confundimento entre fase temporal e configuração e o tamanho reduzido da fase base;
- não atribuirá diferenças científicas ao output cap.

## 13. Outputs previstos

### 13.1 Tabelas

**Tabela A — Integridade e amostra**

- coortes, universo, conjunto principal, conjunto pareado e DPCA ampliada;
- denominadores, missingness e provenance;
- attempts históricas apenas como índice operacional.

**Tabela B — H1 TARGET**

- indicação bruta, confirmação e ausência de confirmação por detector;
- contagem, denominador, proporção e IC95%.

**Tabela C — False alarms NORMAL HOLDOUT**

- indicação bruta e falso alarme confirmado por detector;
- contagem, denominador, proporção/risco de trajetória e IC95%.

**Tabela D — Falso alarme TARGET pré-onset**

- indicação bruta e confirmação indevida em samples 1..160;
- LLM, DPCA pareada e DPCA ampliada em blocos separados.

**Tabela E — H2 delays TARGET**

- denominador total, eventos e denominador condicional;
- mediana/IQR, média/DP, mínimo/máximo e IC95% quando definidos.

**Tabela F — Comparação pareada LLM × DPCA**

- tabelas 2×2 pareadas, discordâncias, diferença pareada e IC95%;
- comparação condicional de delays onde definida.

**Tabela G — H3 groundedness**

- coverage, runs aplicáveis, `run_score` por run, distribuição macro e macro mean;
- agregado micro apenas como secundário com denominador explícito;
- auditoria qualitativa de observation/unsupported process claims separada do score primário.

**Tabela H — DPCA ampliada**

- estimativas TARGET e NORMAL HOLDOUT nas 500 runs de cada coorte;
- claramente separadas do subconjunto pareado de 50.

**Tabela I — Provenance e incidentes**

- emenda, configuração base/efetiva, attempts históricas, reuse immutable e anomalias operacionais não invalidantes.

### 13.2 Gráficos predefinidos

Sem criá-los nesta etapa, ficam previstos:

1. diagrama de fluxo das populações e denominadores;
2. forest/dot-whisker de proporções com IC95%;
3. gráfico de concordância/discordância pareada por endpoint;
4. ECDF de delays condicionais por detector, acompanhada de denominadores;
5. gráfico pareado das diferenças de delay nas runs com ambos os eventos;
6. distribuição por run dos `run_score` H3, sem pseudorreplicação por evidence item;
7. painel contextual DPCA ampliado, visualmente separado da comparação principal;
8. linha de provenance e incidentes operacionais, sem apresentá-los como resultados científicos.

Não serão produzidos gráficos por janela que sugiram independência inferencial.

## 14. Reprodutibilidade e gate de execução

Antes de qualquer análise agregada, o processo futuro deverá:

1. verificar o commit e SHA-256 do `FINAL_CAMPAIGN_MANIFEST` informados neste plano;
2. verificar o hash deste SAP e registrar o commit que o congelar;
3. confirmar 1.000 pares únicos `(cohort, simulationRun)`;
4. confirmar 1.000 resultados DPCA e 50 + 50 resultados LLM;
5. operar em modo read-only sobre resultados e checkpoints;
6. abortar em qualquer divergência de hash, seleção, marker ou manifest;
7. registrar versões do código e bibliotecas estatísticas;
8. emitir primeiro uma tabela de denominadores, antes de qualquer estimativa de efeito.

Qualquer desvio deste plano deverá ser identificado, datado e justificado como emenda analítica prospectiva ou desvio pós-inspeção. Um desvio pós-inspeção não poderá ser apresentado como decisão pré-especificada.

## 15. Regras de interpretação

É proibido:

- inferir causalidade não sustentada pelo desenho;
- assumir independência estatística entre janelas da mesma run;
- afirmar que a LLM não recebeu informação derivada da referência normal — a representação é normal-reference standardized;
- afirmar que a LLM identificou especificamente IDV(13) quando o output apenas classifica evidência de anomalia;
- atribuir diferença de delay confirmado exclusivamente ao detector bruto quando as regras de confirmação diferem;
- tratar execução local/offline isoladamente como novidade científica suficiente;
- promover incidentes, tempo de execução, output cap ou estabilidade operacional a evidência científica;
- generalizar a comparação LLM × DPCA além das populações e seleções formais;
- generalizar os resultados TEP diretamente para processos industriais reais;
- confundir ausência de significância com equivalência ou ausência de efeito;
- transformar análises exploratórias em confirmatórias.

Resultados futuros deverão distinguir estimativa, incerteza, teste e interpretação, mantendo explícitos todos os denominadores e condicionamentos.

## 16. Declaração de gate

```text
AGGREGATE_RESULTS_INSPECTED = NO
STATISTICAL_ANALYSIS_STARTED = NO
PLAN_FROZEN_BEFORE_AGGREGATION = YES
```
