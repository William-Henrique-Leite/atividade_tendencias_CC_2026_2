# Plano de continuidade

Fonte da nova rodada: PDF compacto de 50 páginas, inventário de 443 trechos e banco Neo4j doacao-compacta.

1. Validar o piloto. Diagnosticar o HTTP 400 do LM Studio. Testar extração estruturada em um artigo com incisos, uma regra com exceção e um registro de tabela convertido. Conferir entidades, relações e evidências literais. Gravar embeddings de amostra e verificar a recuperação e as referências.
2. Completar o Text-to-Graph. Processar os 443 trechos com cache e retomada. Revisar saídas vazias, negações, prazos e exceções. Resolver entidades equivalentes, preservar regras distintas e carregar relações com proveniência. Gerar os embeddings restantes. Verificar unicidade, índices de propriedades, full-text e vetor, cobertura e idempotência da carga.
3. Implementar recuperação. No RAG tradicional, recuperar até cinco trechos por cosseno e exibir as referências. No GraphRAG, interpretar a intenção, gerar e validar Cypher, executar em leitura com parâmetros e limites, combinar vetor e Cypher e percorrer pelo menos dois saltos. Aplicar um algoritmo de seleção de caminhos, como Shortest Path.
4. Integrar o Streamlit. Uma pergunta alimenta as duas abas. Exibir trechos, fontes, Cypher executado e subgrafo efetivamente usado, além de similaridade e cobertura. Tratar perguntas fora do tema e evidência insuficiente. A aptidão é decidida na triagem.
5. Avaliar com as perguntas do autor. Usar a mesma versão do corpus, banco e modelo. Conferir evidência, citações, exceções, omissões e afirmações sem respaldo. Atualizar GitHub e README, artigo e apresentação. Registrar que o conteúdo exclusivo das imagens ficou fora do corpus compacto.

## Resultado do piloto de segmentação

Os recortes menores do art. 51 e do registro de corticosteroides sistêmicos retornaram JSON com evidência literal. O teste controlado com tipos fixos ainda apresentou inversão ou preenchimento incorreto de origem e destino. Os resultados estão em dados/compacta/piloto_segmentacao.json e permanecem fora da carga do grafo. O critério para concluir o piloto inclui verificar direção, papéis semânticos e cobertura de condições e exceções, além da evidência literal.

O lote de extração automática dos trechos completos confirmou timeout no art. 51 e no registro de medicamentos. A revalidação do art. 203 aceitou uma relação em cache com evidência literal, mas deixou a exceção apenas na citação. O próximo ajuste é enviar unidades menores com o contexto necessário e validar as relações de exceção antes de ampliar a rodada.

## Integração da versão compacta

O Streamlit usa o banco doacao-compacta e consulta caminhos de até dois saltos. O teste com o art. 203 confirmou o retorno de caminhos de dois saltos. O teste das duas abas passou com Neo4j real e chamadas ao LM Studio simuladas. A carga consolidou a citação duplicada do art. 203 e manteve cinco relações candidatas em duas execuções.

A última contagem confirmada foi de 96 embeddings para 443 trechos. A indexação sofreu timeout no LM Studio e pode ser retomada com python indexar_vetores.py --compacta. A extração segmentada, a geração de Cypher pelo Gemma e a avaliação comparativa ainda estão pendentes.
