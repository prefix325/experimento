# Statistical Analysis Plan — campanha formal TEP/LLM/DPCA

## Status e proveniência

- Tipo: plano estatístico prospectivo, anterior à inspeção dos resultados agregados.
- Corpus: campanha formal concluída, auditada e congelada.
- `FINAL_CAMPAIGN_MANIFEST` commit: `3083558c1aac86508ed7e4fbc9f9b2b33696e701`.
- `FINAL_CAMPAIGN_MANIFEST` SHA-256: `d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5`.
- Method freeze: `TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH`.
- Nível nominal dos intervalos: 95%, bilateral.
- Este plano não contém estimativas, contagens de eventos, taxas, delays observados, testes ou conclusões da campanha.

O objetivo é fixar estimandos, denominadores, regras de inclusão, métodos de incerteza e outputs antes da agregação. Contratos congelados e regras nativas dos detectores prevalecem sobre este documento. Nenhum threshold científico será criado ou redefinido durante a análise.

## 1. Unidade inferencial

A unidade inferencial primária é a `simulationRun`.

Janelas dentro de uma run são observações temporais dependentes da mesma trajetória. Elas não serão tratadas como réplicas independentes, não aumentarão artificialmente o tamanho amostral e não serão reamostradas isoladamente. `FIRST_INDICATION`, `CONFIRMED_DETECTION`, alarmes DPCA brutos e confirmações DPCA pertencem à trajetória que os originou.

Quando evidências ou janelas forem resumidas, sua estrutura será preservada como:

```text
evidence item ⊂ window ⊂ simulationRun
```

Bootstrap, intervalos e comparações que utilizem reamostragem operarão no nível da run. Na comparação pareada, o par LLM–DPCA da mesma `simulationRun` será reamostrado como um único cluster.

## 2. Populações e conjuntos de análise

### 2.1 LLM formal

- TARGET: as 50 runs determinadas por `formal_run_selection.json`.
- NORMAL HOLDOUT: as 50 runs determinadas por `formal_normal_holdout_selection.json`.
- Todas as 100 runs selecionadas pertencem ao conjunto principal LLM; nenhuma exclusão será baseada no resultado.

### 2.2 DPCA formal

- TARGET: 500 runs.
- NORMAL HOLDOUT: 500 runs.
- Total DPCA ampliado: 1.000 runs.

### 2.3 Comparação principal LLM × DPCA

A comparação principal será pareada por `simulationRun` no subconjunto comum:

- TARGET: as mesmas 50 runs selecionadas para a LLM.
- NORMAL HOLDOUT: as mesmas 50 runs selecionadas para a LLM.

O pareamento não poderá ser substituído por comparação entre amostras independentes.

### 2.4 DPCA ampliada

As 500 TARGET e 500 NORMAL HOLDOUT da DPCA serão usadas como contexto e estimativa ampliada da referência estatística DPCA. Essa análise não substituirá a comparação pareada principal e não será apresentada como se tivesse o mesmo desenho da avaliação LLM com 50 runs por coorte.

### 2.5 Regra geral de inclusão

Será usada a attempt científica final referenciada pelo `COMPLETE.json` e pelo `FINAL_CAMPAIGN_MANIFEST`. Attempts históricas `FAILED`, `FAILED_TO_START`, `ABORTED` ou `PARTIAL` serão mantidas apenas como provenance operacional. Nenhum artefato parcial será combinado com a attempt final.

## 3. Definições operacionais dos endpoints

As regras de confirmação permanecem as regras nativas congeladas de cada sistema.

### 3.1 LLM

- Indicação bruta: existência de `FIRST_INDICATION` persistida na run.
- Detecção confirmada: existência de `CONFIRMED_DETECTION` persistida segundo `FIRST_INDICATION_CONCURRENT_FULL_SAMPLE_REFRESH_V1`.
- Sem confirmação: ausência de `CONFIRMED_DETECTION` ao término da trajetória.
- Em NORMAL HOLDOUT, os mesmos estados serão descritos como indicação bruta de falso alarme e falso alarme confirmado.

### 3.2 DPCA

- Indicação bruta: primeiro alarme DPCA bruto segundo o contrato congelado.
- Detecção confirmada: primeiro alarme que satisfaz a persistência nativa de três amostras consecutivas.
- Sem confirmação: ausência de alarme persistente até o término da trajetória.
- Em NORMAL HOLDOUT, os endpoints serão denominados indicação bruta de falso alarme e falso alarme confirmado.

Não será criada equivalência semântica entre a lógica interna dos dois detectores. A comparação será entre endpoints de função correspondente — bruto e confirmado — preservando as regras nativas.

## 4. H1 — detecção e falso alarme

H1 será tratada por estimação descritivo-inferencial. Não haverá threshold retrospectivo para declarar uma hipótese “aceita” ou “rejeitada”.

### 4.1 TARGET

Para cada detector e conjunto de análise serão reportados:

1. proporção de runs com indicação bruta/`FIRST_INDICATION`;
2. proporção de runs com detecção confirmada;
3. proporção de runs sem confirmação.

O denominador principal LLM e da comparação pareada DPCA será sempre 50, inclusive quando não houver evento. Na análise DPCA ampliada, o denominador TARGET será 500.

Endpoint primário TARGET: detecção confirmada por run. Indicação bruta e ausência de confirmação serão endpoints secundários predefinidos.

### 4.2 NORMAL HOLDOUT

Para cada detector serão reportados:

1. proporção de runs com indicação bruta de falso alarme;
2. proporção de runs com falso alarme confirmado;
3. proporção sem falso alarme confirmado.

O denominador principal LLM e pareado DPCA será 50. Na análise DPCA ampliada, o denominador NORMAL HOLDOUT será 500.

Endpoint primário NORMAL HOLDOUT: falso alarme confirmado por run. Indicação bruta será endpoint secundário.

### 4.3 Forma de apresentação

Cada proporção será apresentada como `eventos / runs elegíveis`, estimativa pontual e intervalo de 95%. A ausência de evento não será removida do denominador.

## 5. H2 — tempo até indicação e confirmação

H2 aplica-se às runs TARGET. Para cada evento persistido:

```text
delay_minutes = (decision_sample_end - 161) * 3
```

Serão calculados separadamente:

- delay até indicação bruta/`FIRST_INDICATION`;
- delay até detecção confirmada.

Para uma run sem o evento correspondente:

- `detected = false`;
- `delay_minutes = null`;
- a run permanece no denominador de detecção;
- a run não entra silenciosamente no denominador do resumo condicional de delay.

Valores negativos, índices impossíveis ou inconsistentes com o contrato serão tratados como falha de integridade, não truncados para zero.

### 5.1 Resumos predefinidos

Entre runs com delay definido, serão apresentados, sempre com o denominador condicional explícito:

- mediana;
- primeiro e terceiro quartis e IQR;
- média;
- desvio-padrão;
- mínimo e máximo;
- intervalo de 95% da mediana e da média por bootstrap no nível da run.

Mediana/IQR e média/desvio-padrão serão reportados conjuntamente; nenhum deles será escolhido ou omitido depois da inspeção da distribuição. Mínimo e máximo não receberão interpretação inferencial.

O delay confirmado é um endpoint do sistema detector + regra de confirmação. Diferenças nele não serão atribuídas exclusivamente ao detector bruto quando as regras de pós-processamento diferirem.

## 6. NORMAL HOLDOUT

Cada trajetória NORMAL HOLDOUT contém 189 janelas e não admite early-stop.

Serão mantidos separadamente:

- qualquer indicação bruta de anomalia;
- falso alarme confirmado pela regra nativa.

Não será calculado delay relativo a fault onset em NORMAL HOLDOUT, pois não existe onset de falha. Tempo ou janela do primeiro falso alarme poderá ser exibido apenas como localização temporal descritiva da run, com denominador explícito, e não como delay de detecção.

O número total de janelas não será usado como `n` inferencial independente.

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

A diferença pareada de proporções receberá intervalo de 95% obtido por reamostragem pareada no nível da `simulationRun`. O teste não converterá a análise em decisão binária de “hipótese aceita”.

### 7.2 Delays pareados

Delays só serão comparados diretamente nas runs em que o mesmo endpoint esteja definido para ambos os detectores. Serão reportados:

- número total de pares elegíveis original;
- número em que nenhum, somente um ou ambos detectaram;
- número de pares com delay definido em ambos;
- diferença pareada `LLM - DPCA` em minutos;
- mediana, IQR, média, desvio-padrão, mínimo/máximo e intervalos por bootstrap pareado.

Essa análise será explicitamente denominada condicional a ambos os eventos terem ocorrido. Ela não substituirá a análise binária de detecção e não será generalizada às runs sem detecção.

Não será criada imputação punitiva de delay para não detecções. Se um teste de localização pareado for apresentado como análise secundária, será usado teste exato de sinais, com zeros e empates documentados, evitando pressupor normalidade ou simetria não verificadas.

### 7.3 Detector bruto versus sistema confirmado

Resultados serão separados em:

- resposta bruta do detector;
- resposta do sistema operacional completo, após a regra nativa de confirmação.

Concordância em um nível não será usada para inferir concordância no outro.

## 8. Incerteza

### 8.1 Proporções

Intervalos primários de 95% para detection, false alarm e no-detection rates usarão o intervalo de Wilson, apropriado para denominadores de 50 e para proporções próximas dos limites. A aproximação normal ingênua `p ± 1,96 × SE` não será o método primário.

Quando a contagem estiver no limite zero ou no denominador total, o intervalo exato de Clopper–Pearson poderá ser apresentado como análise de sensibilidade, identificado como conservador e sem substituir Wilson.

### 8.2 Bootstrap

- Número predefinido de réplicas: 10.000.
- Seed predefinido: `20260820`.
- Intervalo preferencial: BCa de 95%; se BCa for matematicamente indefinido, usar percentil de 95% e registrar a razão.
- Unidade de reamostragem: `simulationRun`.
- Comparações: reamostragem do par LLM–DPCA como cluster indivisível.
- H3: reamostragem de runs inteiras, preservando janelas e evidence items dentro da run.

Nenhum bootstrap será realizado por janela independente.

## 9. H3 — process-evidence groundedness

H3 seguirá exclusivamente o contrato e os thresholds já congelados. Não serão criados novos limiares a partir dos resultados.

Cada evidence item será avaliado quanto a:

1. existência da variável citada no vocabulário/representação permitida;
2. compatibilidade entre claim/direção e os valores representados;
3. suporte da magnitude ou desvio alegado;
4. presença de unsupported process claims.

### 9.1 Agregação hierárquica

A agregação primária será no nível da run. Para cada run, serão preservados:

- número de janelas com evidence;
- número de evidence items avaliáveis;
- fração de variáveis citadas válidas;
- fração de claims/direções compatíveis;
- fração de magnitudes/desvios suportados;
- fração de unsupported process claims;
- contagens e denominadores de cada métrica.

O resumo entre runs será macro: cada run elegível terá peso igual. Distribuições entre runs e intervalos por bootstrap de runs serão apresentados. Um agregado micro por evidence item poderá ser secundário, desde que explicitamente rotulado e acompanhado de seu denominador; ele não substituirá o resumo por run.

Evidence items, janelas e claims não serão tratados como observações inferenciais independentes. Ausência de evidence produzirá métrica `null` quando o denominador for zero, acompanhada da contagem de runs afetadas; não haverá imputação ad hoc.

## 10. Multiplicidade e classificação das análises

### 10.1 Primárias

- TARGET: detecção confirmada por run, por detector e diferença pareada LLM–DPCA.
- NORMAL HOLDOUT: falso alarme confirmado por run, por detector e diferença pareada.
- TARGET H2: estimação condicional predefinida do delay confirmado, sem decisão binária de hipótese.
- H3: métricas macro por run definidas pelo contrato congelado.

### 10.2 Secundárias

- indicações brutas;
- delays até primeira indicação;
- concordância e discordâncias adicionais;
- DPCA ampliada em 500 + 500 runs;
- análise de sensibilidade de provenance da emenda.

### 10.3 Exploratórias

Qualquer estratificação, diagnóstico de distribuição ou visualização não listada neste plano será marcada como exploratória. Análises exploratórias não serão promovidas a confirmatórias.

O plano não estabelece thresholds para “aceitar” H1, H2 ou H3. Se p-values forem reportados para os dois contrastes binários primários — detecção confirmada TARGET e falso alarme confirmado NORMAL HOLDOUT — eles formarão uma única família e serão ajustados pelo método de Holm. P-values secundários ou exploratórios, se excepcionalmente produzidos, serão separados por família, ajustados por Holm e claramente rotulados; não serão misturados com a família primária.

Intervalos descritivos serão apresentados com transparência sobre multiplicidade e não reinterpretados como testes independentes não ajustados.

## 11. Dados ausentes e runs sem evento

- `no detection`: resultado binário válido, não dado ausente.
- Ausência de `FIRST_INDICATION`: indicação bruta `false`; delay correspondente `null`.
- Ausência de confirmation: confirmação `false`; delay confirmado `null`.
- Run com indicação mas sem confirmação: permanece no denominador de indicação e de confirmação, com confirmação `false`.
- Delay `null`: não será convertido em zero, máximo, infinito ou valor arbitrário.
- Ausência de evidence H3 com denominador zero: métrica H3 `null`, com motivo e contagem explícitos.
- Arquivo ou campo obrigatório ausente contra o manifest: falha de integridade; a análise deve parar em vez de imputar.
- Nenhuma exclusão ou imputação será determinada depois da observação do efeito sobre os resultados.

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
- contagem, denominador, proporção e IC95%.

**Tabela D — H2 delays TARGET**

- denominador total, eventos e denominador condicional;
- mediana/IQR, média/DP, mínimo/máximo e IC95%.

**Tabela E — Comparação pareada LLM × DPCA**

- tabelas 2×2 pareadas, discordâncias, diferença pareada e IC95%;
- comparação condicional de delays onde definida.

**Tabela F — H3 groundedness**

- métricas por run e distribuição macro entre runs;
- agregado micro apenas como secundário com denominador explícito.

**Tabela G — DPCA ampliada**

- estimativas TARGET e NORMAL HOLDOUT nas 500 runs de cada coorte;
- claramente separadas do subconjunto pareado de 50.

**Tabela H — Provenance e incidentes**

- emenda, configuração base/efetiva, attempts históricas, reuse immutable e anomalias operacionais não invalidantes.

### 13.2 Gráficos predefinidos

Sem criá-los nesta etapa, ficam previstos:

1. diagrama de fluxo das populações e denominadores;
2. forest/dot-whisker de proporções com IC95%;
3. gráfico de concordância/discordância pareada por endpoint;
4. ECDF de delays condicionais por detector, acompanhada de denominadores;
5. gráfico pareado das diferenças de delay nas runs com ambos os eventos;
6. distribuição por run das métricas H3, sem pseudorreplicação por evidence item;
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
- confundir ausência de significância com equivalência ou ausência de efeito;
- transformar análises exploratórias em confirmatórias.

Resultados futuros deverão distinguir estimativa, incerteza, teste e interpretação, mantendo explícitos todos os denominadores e condicionamentos.

## 16. Declaração de gate

```text
AGGREGATE_RESULTS_INSPECTED = NO
STATISTICAL_ANALYSIS_STARTED = NO
PLAN_FROZEN_BEFORE_AGGREGATION = YES
```
