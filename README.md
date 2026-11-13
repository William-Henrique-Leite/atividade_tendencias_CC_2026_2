# Assistente de orientação à doação de sangue

Aplicação acadêmica em Streamlit para consultar a Portaria GM/MS nº 11.685/2026 e comparar duas estratégias de recuperação. O RAG combina busca textual e vetorial com Reciprocal Rank Fusion (RRF). O GraphRAG acrescenta relações com evidência textual e caminhos de até dois saltos. O Gemma gera as respostas em português. A aptidão final cabe à triagem do hemocentro.

## Pré-requisitos

- Python 3.14.2 e Streamlit 1.57.0 foram usados na máquina do projeto.
- Neo4j Desktop com instância local. A carga automatizada cria o banco doacao-compacta e requer uma edição que permita múltiplos bancos e uma conta com permissão de criação. O ambiente registrado no projeto usou Neo4j 2026.10.2 Enterprise.
- LM Studio com servidor em http://127.0.0.1:1234 e modelos gemma-4-e4b-it e text-embedding-nomic-embed-text-v1.5. Carregue o Gemma com contexto de 4.096 tokens. O Nomic gera vetores de 768 dimensões.
- Os dois PDFs e os arquivos de dados do projeto. A versão compacta de 50 páginas é o corpus pesquisável. O original de 71 páginas permite conferir as células e a paginação. Para reproduzir o grafo já construído, preserve também os JSON de extração e de relações documentais.

## Instalação local

No PowerShell, abra a pasta que contém app.py e execute:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Se já existir um .env, preserve-o e confira seus valores. Configure NEO4J_URI, NEO4J_USER e NEO4J_PASSWORD conforme a instância. Mantenha .env fora do controle de versão. O aplicativo usa doacao-compacta por padrão. DOACAO_APP_DATABASE altera o banco da interface, enquanto os comandos de carga com --compacta usam doacao-compacta. Se o LM Studio apresentar outro identificador para o Gemma, configure LM_STUDIO_CHAT_MODEL no ambiente do processo antes de iniciar os scripts.

Inicie a instância no Neo4j Desktop. No LM Studio, carregue os dois modelos e inicie o servidor. Confira os identificadores disponíveis:

```powershell
(Invoke-RestMethod 'http://127.0.0.1:1234/v1/models').data.id
```

## Reproduzir o banco e executar o aplicativo

O PDF Portaria GM-MS 11685 - versao compacta.pdf deve estar na raiz. Os comandos abaixo geram o inventário, carregam os dados disponíveis e indexam os trechos sem vetor. Se o banco e os índices já estiverem prontos, execute apenas o último comando.

```powershell
.\.venv\Scripts\python.exe pipeline_gemma.py --compacta --inventario
.\.venv\Scripts\python.exe carregar_integral.py --compacta
.\.venv\Scripts\python.exe indexar_vetores.py --compacta
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

Abra http://127.0.0.1:8502. Mantenha o Streamlit, o Neo4j e o LM Studio ativos durante as consultas. O inventário sozinho permite carregar e indexar o texto. A reprodução das relações existentes exige os arquivos dados/compacta/extracoes.json e dados/compacta/relacoes_piloto_validadas.json.

Para reconstruir as relações documentais, use dados/integral/tabelas.json ou regenere esse arquivo a partir do PDF original. Substitua o caminho de exemplo pelo caminho real do original:

```powershell
.\.venv\Scripts\python.exe extrair_tabelas.py 'C:\caminho\para\o\original.pdf'
.\.venv\Scripts\python.exe validar_piloto_compacto.py
.\.venv\Scripts\python.exe carregar_integral.py --compacta
```

Para gerar novas relações candidatas com o Gemma, execute pipeline_gemma.py --compacta --limite 5 com o mesmo Python. O cache permite retomar o processamento. Revise direção, condições, exceções e evidências antes da carga. O PDF compacto já contém as tabelas em texto, portanto esta rodada usa --compacta sem --tabelas.

## Verificação e solução de problemas

No Neo4j Desktop, selecione doacao-compacta e execute:

```cypher
MATCH (t:TrechoIntegral)
RETURN count(t) AS trechos, count(t.embedding) AS vetores
```

```cypher
SHOW INDEXES YIELD name, type, state
RETURN name, type, state ORDER BY name
```

A rodada do projeto tem 443 trechos e 443 vetores. Confirme que trecho_texto e trecho_vetor estão ONLINE. Envie uma pergunta no Streamlit e confira o método de busca, os três scores RRF, as fontes e a resposta. Na aba GraphRAG, confira as entidades e os caminhos quando houver relações para o tema.

| Sintoma | Verificação |
|---|---|
| Conexão Bolt recusada | Inicie a instância e confira a URI no .env. |
| Modelo indisponível | Confira o servidor na porta 1234 e os identificadores em /v1/models. |
| Busca sem trechos | Confira o banco selecionado, a carga e o estado dos índices. |
| Resposta truncada | Confira max_tokens na função ask_model do app.py. O teto de saída é independente da janela de contexto do Gemma. |
| Timeout de geração | Confira se o Gemma está ocupado e se o contexto cabe no modelo carregado. A interface mantém as fontes recuperadas. |

## Implantação em máquina virtual

A implantação local foi usada no projeto. Para uma implantação em nuvem, use uma máquina virtual com ambiente gráfico compatível para executar o LM Studio e recursos suficientes para carregar os dois modelos. Instale Neo4j, Python e as dependências na VM, transfira os PDFs e os JSON e siga a mesma sequência de carga. O cliente atual usa o endereço de loopback fixo para o LM Studio, portanto mantenha o serviço de modelos e o Streamlit na mesma VM. Configure a URI do Neo4j de acordo com a instalação escolhida.

Mantenha o Streamlit ligado a 127.0.0.1 e acesse a porta 8502 por um túnel SSH quando houver acesso SSH à VM:

```text
ssh -N -L 8502:127.0.0.1:8502 usuario@host-da-vm
```

Abra http://127.0.0.1:8502 na sua máquina enquanto o túnel estiver ativo. Para uso compartilhado, configure autenticação e HTTPS em um proxy reverso. A implantação em nuvem está documentada como procedimento e ainda não foi validada no projeto.

## Relatório técnico

Consulte o [relatório técnico final](relatorio-tecnico-final.md) para metodologia, modelagem, resultados observados e limitações.
