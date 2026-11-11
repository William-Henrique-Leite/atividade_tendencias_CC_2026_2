# Assistente de orientação à doação de sangue

## Etapa 1 — Extração e segmentação do PDF

O script lê as páginas 7 e 8 da cópia em PDF da Portaria GM/MS nº 11.685/2026. O recorte inclui a triagem (art. 36), a frequência e o intervalo entre doações (art. 38), idade e primeira doação (art. 39) e peso (art. 40). O documento de origem fica na raiz do projeto.

### Executar

No PowerShell, dentro desta pasta:

```powershell
python -m pip install -r requirements.txt
$pdf = (Get-ChildItem -File -Filter *.pdf | Select-Object -First 1).FullName
python extrair_trechos.py "$pdf"
```

A saída padrão é `dados/trechos.json`. Cada trecho tem ID estável, identificação do artigo e parágrafo, número da página e texto. Os metadados do documento incluem a URL institucional, o número de páginas e o SHA-256 do arquivo. O script usa a paginação desta cópia e verifica se o conjunto esperado de artigos e parágrafos foi extraído.

### Resultado verificado

A execução com o PDF do projeto gerou 15 trechos únicos. O caput do art. 36 foi localizado na página 7, e seus parágrafos na página 8. Os arts. 38 a 40 e seus parágrafos estão na página 8. A conferência confirmou que os cabeçalhos e rodapés de impressão ficaram fora dos trechos e que uma nova execução produz o mesmo resultado.

A próxima etapa é extrair as entidades e as regras com um modelo de linguagem e revisar as condições, exceções e evidências antes da carga no Neo4j. O escopo do assistente inclui outros requisitos e impedimentos, a incorporar em lotes após o primeiro fluxo.

[Texto da portaria no Ministério da Saúde](https://bvsms.saude.gov.br/bvs/saudelegis/gm/2026/prt11685_03_07_2026.html)
