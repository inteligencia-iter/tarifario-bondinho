# Conhecimento Técnico Consolidado — Monitor de Tarifário

Este documento existe para que o conhecimento acumulado durante a
investigação técnica não dependa de memória de conversa. Qualquer pessoa
(ou instância futura do Claude) deveria conseguir entender e dar
manutenção no projeto lendo só este arquivo + o `PLAYBOOK_INVESTIGACAO.md`.

## Contexto e objetivo

Grupo Iter opera atrativos turísticos no Rio de Janeiro (Parque Bondinho
Pão de Açúcar, entre outros). O objetivo deste projeto é monitorar
mensalmente o tarifário de concorrentes (e do próprio negócio), de forma
automatizada, para análise de variação de preços, sazonalidade e
posicionamento competitivo — incluindo séries temporais MoM (mês a mês) e
YoY (ano a ano).

## Mecanismo Limber Software (o mais complexo, cobre 3 dos 6 atrativos do RJ)

Confirmado em: Paineiras-Corcovado, AquaRio, BioParque do Rio. Todos
tenants da mesma plataforma SaaS de bilheteria ("Limber Software").

### Autenticação e criptografia

Toda comunicação de API usa um payload cifrado com **AES-CBC**, no formato
`CryptoJS.AES.encrypt(texto, senha).toString()` do JavaScript — que produz
uma string Base64 começando com `Salted__` seguida de 8 bytes de salt e o
texto cifrado. A derivação de chave usa **EVP_BytesToKey com MD5** (padrão
OpenSSL clássico, 1 iteração) — isso está implementado em
`scripts/decrypt_limber.py` (`_evp_bytes_to_key`, `decrypt_cryptojs`,
`encrypt_cryptojs`).

Isso NÃO é um segredo forte: a "senha"/chave usada em cada requisição é
obtida de um endpoint público (`env.cryptoKey`, ver abaixo), então não há
segredo real protegendo o payload — é ofuscação, não segurança de fato.

### Sequência de chamadas

1. **Config do tenant** — `GET /uploads/ec-config/{hostname}/PT/config`.
   Resposta cifrada com uma chave FIXA (a mesma para todos os tenants):
   `ecck-SV6QdGk1NCg1NaXzQ`. Decriptando, o JSON retorna:
   - `env.cryptoKey`: a chave usada para cifrar TODO o resto das chamadas
     deste tenant específico.
   - `geral.token`: um JWT usado como `Authorization: Bearer` em todas as
     chamadas seguintes.
   - `geral.idParceiro`: ID numérico do tenant, usado em quase todos os
     payloads.
   - `geral.nomeEmpresa`: nome de exibição do tenant.

2. **CSRF** — `GET /api/auth/csrf?xlh={valor}`, onde `xlh` é
   `base64(hostname_com_string_invertida)` (ex: para
   `ingressos.aquariomarinhodorio.com.br`, inverte a string toda e
   codifica em Base64). Essa fórmula está em `host_signature()` em
   `decrypt_limber.py`. A resposta traz `{"csrfToken": "..."}` no **corpo
   JSON** — não confundir com o cookie `XSRF-TOKEN` que a mesma resposta
   também seta (o cookie NÃO é o que se usa aqui; foi uma fonte de erro
   real durante a investigação).

3. **Headers para todas as chamadas seguintes:**
   ```
   Authorization: Bearer {geral.token}
   x-xsrf-token: {csrfToken do passo 2}
   x-l-h: {mesmo valor xlh do passo 2}
   Content-Type: text/plain
   ```
   O `Content-Type: text/plain` é proposital — o corpo da requisição é uma
   string cifrada, não JSON estruturado, então o servidor espera texto puro.

4. **Catálogo** — `POST /api/cross/consulta/allsku`, corpo cifrado
   `{"idparceiro": <id>}`. Retorna lista de produtos (SKU, nome, categoria)
   SEM preço.

5. **Detalhe do produto** — `POST /api/cross/consulta/sku`, corpo cifrado
   `{"sku": <sku>, "idparceiro": <id>}`. Retorna o produto completo,
   incluindo:
   - `categorias`: lista de categorias de ingresso com `valorUnitario`
     (preço "de catálogo" — ver nota de discrepância abaixo).
   - `temporadas`: lista de temporadas configuradas (nome, `tipoReceita`).
   - `locaisEmbarque`: lista de pontos de embarque, se o produto tiver mais
     de um (só visto no Cristo Redentor via Paineiras-Corcovado).

6. **Preço por variante (embarque OU data específica)** —
   `POST /api/cross/consulta/configpreco`. Este é o endpoint mais
   importante para análise de preço real, e o único jeito de capturar
   variações que o preço "de catálogo" (`categorias` do passo 5) não
   reflete. Dois usos:
   - **Preço por local de embarque:** payload
     `{"idParceiro", "data", "dataFim", "sku", "receita", "localEmbarque", "meioVenda": "WEB"}`
     com `localEmbarque` = 1, 2, 3... (índice do local, na ordem retornada
     em `locaisEmbarque` do passo 5).
   - **Preço por data (sazonalidade / antecedência de compra):** mesmo
     payload, mas com `localEmbarque: null` e variando `data`/`dataFim`
     para a data de visita desejada.

### Discrepância importante: preço "de catálogo" vs. preço real

O campo `categorias[].valorUnitario` do passo 5 (`consulta/sku`) e o preço
retornado por `configpreco` (passo 6) podem divergir. Exemplo real
confirmado no BioParque do Rio: `categorias` mostra Adulto = R$39,90, mas
`configpreco` para qualquer data real de visita retorna R$55, R$62 ou R$69
dependendo da temporada/antecedência. Isso significa que `categorias` NÃO
deve ser usado como o preço de venda real para análise — é algum tipo de
valor de referência ou configuração de tabela cheia, não o preço
efetivamente cobrado. Sempre priorizar `configpreco` quando disponível.

O motivo de `categorias` ainda estar no schema/coleta é que ele lista todas
as categorias configuradas (incluindo promoções específicas de data como
"Dia das Mães", "Rock in Rio", etc.), o que é útil para saber que
categorias existem, mesmo que o valor não seja o real cobrado hoje.

### Casos especiais descobertos (todos via configpreco)

**Preço por local de embarque (Paineiras-Corcovado, SKU 3073 "Ingresso
Cristo Redentor"):** o único produto no RJ com múltiplos embarques.
Paineiras Corcovado é ~R$45 mais barato (em todas as categorias) do que
Largo do Machado ou Copacabana — esses dois têm preço idêntico entre si.
Disponibilidade de vagas é igual nos 3 embarques; só o preço muda.

**Sazonalidade Alta/Baixa (BioParque do Rio, SKU 8413 e combos
derivados):** temporadas com nome contendo "alta"/"baixa" (detectável via
regex) indicam variação de preço por data. No RJ, o padrão observado é
fim de semana = alta, dia de semana = baixa. Meses inteiros podem ser 100%
alta (ex: julho) ou mistos (ex: agosto).

**D0 vs. D+1 (antecedência de compra) — BioParque do Rio:** comprar no
mesmo dia da visita (D0) é mais caro que comprar com qualquer antecedência
(D+1 em diante). Importante: essa majoração de D0 se aplica SOMENTE à
categoria Adulto/Inteira — as demais categorias (Infantil, Idoso, PCD,
Meia Entrada) variam só por temporada, não por antecedência. Confirmado
lendo a descrição textual do próprio produto no site, que menciona
explicitamente "Comprando antecipado pelo site: Inteira de R$X por R$Y"
sem mencionar as demais categorias. Combos que incluem o BioParque
herdam a sazonalidade Alta/Baixa, mas NÃO a majoração D0 (confirmado:
descrição do combo não menciona nenhuma oferta de antecedência).

**Combos com múltiplas atrações (ex: BioParque + Cristo Redentor):**
podem ter mais de um conjunto de temporadas, um por `tipoReceita` (uma
"receita" = uma atração dentro do combo). É preciso identificar qual
`tipoReceita` corresponde a qual atração antes de assumir que a
sazonalidade se aplica a todo o combo.

## Mecanismo API JSON aberta (Bondinho Pão de Açúcar)

O próprio site do negócio do usuário usa uma API própria sem qualquer
autenticação: `POST https://backend.bondinho.com.br/api/Products/GetProductsRangeFromCategories`
com corpo `{"categoryCode": ["CAT-SITEUN91434"], "channel": 2, "lang": "BR"}`.
Um único `categoryCode` já retorna o catálogo completo (6 produtos).
Resposta inclui `productCode` (identificador estável, útil como chave
para série histórica) e preços por categoria (`minPriceAdult`,
`minPriceChild`, `minPriceElders`).

## Mecanismo HTML via POST simples (Trem do Corcovado)

`POST https://www.tremdocorcovado.rio/Home/getTicket`, sem corpo, apenas
o header `X-Requested-With: XMLHttpRequest`. Retorna um fragmento HTML
(não JSON) com uma `<div class="row">` por categoria de ingresso, nome em
`<h5>`, preço em `<span class="amount">` (formato `R$ 134,00`, precisa
converter vírgula para ponto antes de parsear como float).

## Caso não resolvido: proteção anti-bot (YupStar Rio)

Cloudflare Turnstile ativo (tela "Executando verificação de segurança"
com checkbox). Testado e confirmado que bloqueia Playwright headless
mesmo com playwright-stealth aplicado. Passa sem problema quando
acessado via navegador real controlado por extensão (Claude in Chrome),
mas isso ainda exige uma sessão interativa, não é automatizável no
coletor mensal por enquanto. Os preços em si estão no HTML estático da
página (não há API JSON separada por trás) — o obstáculo é só passar pelo
desafio anti-bot. Empresa controladora: Grupo Gramado Parks.

Caminhos possíveis não testados: serviço pago de resolução de
Turnstile/CAPTCHA (2captcha, CapMonster), ou verificar se o grupo
controlador tem uma API compartilhada entre suas marcas em outro domínio
sem essa proteção.

**Investigação adicional (julho/2026):**
- Confirmado com `curl` simulando User-Agent de navegador real: bloqueio
  retorna HTTP 403 com corpo de "challenge" (~5.6KB), mesmo sem
  automação real por trás — ou seja, o bloqueio de bot da Cloudflare
  aqui reage a sinais de baixo nível (TLS fingerprint / falta de
  execução de JS), não só a `navigator.webdriver`.
- Testado via um navegador Chrome real controlado por extensão (Claude
  in Chrome): a página carrega normalmente (HTTP 200), sem tela de
  desafio, com todos os preços visíveis no HTML (confirmados nesta
  sessão: Adulto R$59,90, Melhor Idade R$39,90, Infantil R$39,90, combo
  "Promoção de Julho" R$79,90). Isso é consistente com a nota anterior
  de que a extensão passa sem problema — reforça que o obstáculo é
  puramente de fingerprint/automação, não autenticação ou geobloqueio.
- `Yup Star Foz` (`foz.yupstar.com.br`, mesma plataforma/grupo) também
  retorna 403 com `curl` — ou seja, não há uma marca-irmã na mesma
  plataforma com proteção mais fraca a explorar.
- `robots.txt` do domínio responde 200 normalmente (não protegido), mas
  `sitemap.xml` retorna 403 — a proteção parece ser por regra de rota
  específica no Cloudflare (paths de conteúdo/página), não bloqueio
  geral do domínio. Não há indício de endpoint JSON alternativo (é uma
  plataforma Django com Filer para mídia, sem API pública encontrada).
- Conclusão: não há atalho técnico barato. As opções reais são (a)
  serviço pago de resolução de Turnstile (2captcha/CapMonster) para
  manter a automação via GitHub Actions, ou (b) coleta semi-manual
  mensal via sessão de navegador real (ex: usando o Claude in Chrome
  interativamente), já que isso comprovadamente funciona.

## Arquitetura de dados: histórico e séries temporais

Banco SQLite (`historico/tarifario.db`) em formato longo: uma linha por
combinação (coleta x concorrente x produto x categoria x variante). A
tabela `precos` tem colunas `variante_tipo` ('embarque', 'temporada',
ou NULL para preço único) e `variante_nome` (ex: 'Copacabana', ou
'Alta - Antecipada (ex: 2026-07-12)'), o que permite representar as
particularidades de cada site sem precisar de colunas dedicadas por tipo
de variante — um novo tipo de variante descoberto no futuro (numa região
nova) se encaixa no schema existente sem migração.

Identificador estável de produto (produto_id): SKU para sites Limber
Software, productCode para o Bondinho, nome do produto para o Trem do
Corcovado (que só tem 1 produto, sem risco de colisão). Isso é o que
permite comparar o "mesmo produto" entre meses diferentes mesmo que o
nome de exibição mude ligeiramente.

Consultas MoM e YoY (historico/analises.py) comparam sempre a
última coleta de cada mês de referência (não todas as coletas), e
usam junção por produto_id + categoria + variante_tipo +
variante_nome — uma mudança de preço só aparece no relatório se o valor
numérico realmente mudou entre as duas coletas comparadas.

## Dashboard (GitHub Pages)

O dashboard em `docs/index.html` é um arquivo único, sem build step,
seguindo o mesmo padrão usado em outros projetos do usuário: React via
CDN (sem Node/npm), Recharts para gráficos, Tailwind CSS via CDN. Consome
`docs/dados_tarifario.json`, gerado por `historico/exportar_para_dashboard.py`
a partir do banco SQLite (o navegador não lê SQLite nativamente sem
WASM, então a exportação para JSON evita essa complexidade desnecessária
dado o volume pequeno de dados).

**Bug crítico de infraestrutura encontrado e corrigido:** a tag
`<script src="https://unpkg.com/@babel/standalone/babel.min.js">`, sem
versão fixada, resolve para a major version 8 do Babel Standalone
(confirmado: `@babel/standalone@8.0.4` no momento da descoberta), que é
incompatível com o padrão clássico de `<script type="text/babel">` — a
página renderiza **completamente em branco**, com o erro
`Cannot use import statement outside a module` no console. Isolado
testando cada script CDN individualmente em uma página mínima. Corrigido
fixando a versão: `@babel/standalone@7/babel.min.js`. Qualquer alteração
futura no dashboard deve manter essa versão fixada — não remover o `@7`.

Também foi necessário adicionar `<script src="https://unpkg.com/prop-types@15/prop-types.min.js">`
antes do Recharts: o bundle UMD do Recharts depende de `prop-types` via
`require()`, e sem essa dependência carregada `PropTypes` fica `undefined`,
gerando o erro `Cannot read properties of undefined (reading 'oneOfType')`.

**Lição de processo:** nenhum desses dois bugs aparecia em inspeção do
código-fonte por leitura, nem em teste de sintaxe — só ficaram visíveis
ao efetivamente renderizar a página num navegador (headless, via
Playwright) e capturar os erros de console/página. Antes de considerar
qualquer alteração no dashboard como "pronta", rodar esse teste de
renderização real é obrigatório, não opcional.



1. **Ambiguidade de receita no cálculo de preço por embarque**: o código
   inicialmente pegava temporadas[0].tipoReceita sem checar se havia
   múltiplas receitas distintas — funcionava por coincidência no
   Paineiras-Corcovado (só 1 receita), mas quebraria silenciosamente em
   um produto com embarque + múltiplas receitas ao mesmo tempo. Corrigido
   para detectar ambiguidade e emitir aviso.

2. **Perda do valor de "alta temporada normal" quando a coleta roda em
   dia de alta temporada**: a lógica original pulava o dia "hoje" ao
   buscar um dia representativo de cada temporada — e como o dia da
   coleta frequentemente coincide com "alta" (fins de semana são maioria
   dos dias de alta), o sistema perdia esse valor por completo, ficando
   só com D0 e Baixa. Corrigido para buscar o próximo dia distinto da
   mesma temporada quando o primeiro dia encontrado coincide com hoje.

3. **Coletas duplicadas no mesmo mês sem aviso**: `coletar_e_registrar.py`
   originalmente não checava se já existia uma coleta para o mês de
   referência antes de inserir uma nova — rodar o script duas vezes por
   engano no mesmo mês criava duas linhas em `coletas` (a consulta MoM/YoY
   ainda funcionava, porque usa `MAX(id_coleta)` por mês, mas isso
   poluía o histórico silenciosamente). Corrigido: o script agora verifica
   se já existe coleta para o mês e aborta com uma mensagem clara, a
   menos que rodado com `--forcar`. Nomes de arquivo em `snapshots_brutos/`
   também passaram a incluir timestamp completo (não só a data), para não
   sobrescrever silenciosamente um snapshot anterior do mesmo dia.

4. **Duplicação da lógica de criptografia entre dois arquivos**:
   `limber_scraper.py` reimplementava toda a lógica de AES/CryptoJS
   (`_evp_bytes_to_key`, `decrypt_cryptojs`, `encrypt_cryptojs`,
   `host_signature`) de forma independente de `decrypt_limber.py`, que já
   continha exatamente a mesma lógica. As duas implementações eram
   funcionalmente idênticas no momento da auditoria, mas isso criava risco
   real de divergência silenciosa (ex: corrigir um bug de criptografia em
   um arquivo e esquecer do outro). Corrigido: `limber_scraper.py` agora
   importa de `decrypt_limber.py` em vez de duplicar. Nesse processo,
   também foi corrigida uma fragilidade latente em `decrypt_limber.py`:
   a tolerância a respostas HTTP com aspas JSON ao redor do valor cifrado
   (formato `'"U2FsdGVkX1..."'`) só existia no bloco de execução via
   linha de comando, não na função `decrypt_cryptojs()` em si — funcionava
   por acidente até então porque `base64.b64decode()` do Python ignora
   silenciosamente caracteres fora do alfabeto Base64 (como aspas), não
   porque havia tratamento explícito. Agora a tolerância está na própria
   função, de forma explícita.

5. **Falso positivo de sazonalidade em produtos sem variação real de
   preço**: o Cristo Redentor (via Paineiras-Corcovado) tem, no sistema
   Limber Software, uma temporada literalmente chamada "Paineiras" (o
   mesmo nome do local de embarque, reaproveitado) e outra chamada "Baixa
   Temporada" — mas nenhuma das duas altera o preço na prática (testado:
   Adulto = R$87 tanto em D0 quanto D+1 quanto em qualquer data). A
   detecção de sazonalidade verificava se a LISTA de temporadas do produto
   continha "alta/baixa" em algum nome, mas depois iterava por TODAS as
   temporadas do calendário (inclusive as sem "alta/baixa" no nome
   individual, como "Paineiras"), gerando entradas de variante espúrias
   que apareciam no dashboard como se fosse uma variação de preço real
   que não existe. Corrigido em duas camadas: (a) o filtro de "esta
   temporada é sazonal" agora é aplicado por nome individual de cada
   ocorrência no calendário, não pela lista inteira do produto; (b) uma
   checagem adicional de sanidade descarta o conjunto de variantes por
   completo se, depois de coletado, nenhuma categoria realmente varia de
   valor entre elas (comparação categoria a categoria, não um pool
   global de valores — um pool global mascarava a ausência de variação
   real porque cada variante já tem múltiplas categorias com valores
   diferentes entre si, mesmo sem variação entre variantes). Esse bug só
   ficou visível ao testar o dashboard visualmente com dados reais — não
   aparecia em nenhuma inspeção anterior do JSON bruto por scripts, só ao
   olhar a tela renderizada.

6. **Race condition de push no workflow do GitHub Actions**: o passo de
   commit original fazia apenas `git commit` + `git push`, sem tratar o
   caso raro de dois disparos concorrentes do workflow (ex: o agendamento
   mensal e um disparo manual coincidindo). Nesse cenário, o segundo
   `push` falharia com erro de "non-fast-forward" e o job terminaria em
   erro sem necessidade real. Corrigido adicionando `git pull --rebase`
   antes do push final.

## Nota operacional sobre `--forcar`

Cada execução de `coletar_e_registrar.py --forcar` cria uma nova linha em
`coletas`, mesmo que os dados coletados sejam idênticos aos da coleta
anterior do mesmo mês — o histórico não deduplica automaticamente por
valor, só por (mês + flag de forçar explícita). Isso é intencional
(permite auditar quantas vezes uma coleta foi tentada), mas significa que
usar `--forcar` repetidamente em testes acumula linhas no banco. Se isso
acontecer, a limpeza é manual: identificar o `id_coleta` indesejado via
`python3 analises.py historico` e remover com
`DELETE FROM precos WHERE id_coleta = X; DELETE FROM coletas WHERE id_coleta = X;`
diretamente no SQLite, e também apagar o arquivo correspondente em
`snapshots_brutos/` para manter os dois em sincronia.

## Dashboard: telas, identidade visual e detecção de campanha (julho/2026)

O dashboard (`docs/index.html`) ganhou navegação por abas: "Visão geral"
(tira de campanhas detectadas por atrativo + tabela completa de tarifário +
variações MoM + variantes) e "Evolução de preço" (seletor
atrativo → produto → categoria, com gráfico de linha da série histórica;
com 1 mês de dado mostra um cartão de valor único em vez de gráfico).

**Identidade visual (atualizado em 2026-07-13):** cor de marca `#ff6600`
(laranja) como destaque principal (linha do gráfico de evolução, aba
ativa, badges de promoção, barras positivas de variação MoM, e agora
também o fundo sólido do header, com texto em branco para contraste).
Fonte: **Poppins** (Google Fonts) em todo o site — decisão final do
usuário, substituindo a escolha provisória anterior (Space Grotesk).
Ofelia Display continua fora de cogitação por ser fonte paga sem CDN
gratuito; a classe `.font-display` permanece como ponto único de troca
caso o usuário obtenha os arquivos da fonte no futuro.

**Detecção de campanha promocional (redesenhada em 2026-07-14):** dois
sinais, em ordem de prioridade:
1. **Sazonalidade** (sinal primário, dado estruturado): `variante_tipo === "temporada"`
   — o próprio modelo de dados já indica que o produto varia de preço por
   época do ano, não é heurística de texto.
2. **Evento/feriado** (sinal secundário, por palavra-chave): regex
   específica para feriados e eventos sazonais reais (férias escolares,
   Dia das Mães/Pais, Carnaval, Independência, Black Friday/November,
   Copa, Rock in Rio, Natal, aniversário) aplicada a `produto_nome`/
   `categoria`; e regex genérica (`promo|campanha`) como último recurso.

**Falso positivo corrigido:** o Parque Bondinho Pão de Açúcar (site
próprio) usa a categoria composta **"Crianca/Promocional"** como nome
padrão do desconto infantil — não é uma campanha pontual, é só a
nomenclatura da faixa etária. A regex genérica de "promo/campanha"
capturava isso incorretamente. Corrigido: a regex genérica só é aplicada
a uma categoria se ela **não contiver "/"** (rótulos compostos de público
como "X/Promocional" ficam de fora desse gatilho genérico; a regex
específica de feriados/eventos continua se aplicando normalmente a
qualquer categoria, composta ou não). Ver funções `ehSazonal`, `ehEvento`,
`categoriaEhEventoGenerico` em `docs/index.html`.

Validado contra o dado real de julho/2026: Bondinho aparece como "Sem
campanha detectada" (correto), enquanto AquaRio/BioParque continuam
sinalizando suas campanhas reais (Dia das Mães, Copa, sazonalidade
Alta/Baixa etc.). É heurística sobre texto livre além do sinal
estrutural de sazonalidade — pode haver falso positivo/negativo pontual
com nomenclaturas muito diferentes de concorrentes futuros.

**Verificação de renderização real:** o sandbox de execução não tinha
Chromium headless funcional (faltavam libs de sistema e o download do
Playwright não trazia o snapshot do V8; sem acesso root para
`apt install`). Em vez de pular a verificação, a renderização foi
validada executando o HTML de fato num DOM real via `jsdom` (Node) com o
`dados_tarifario.json` real do projeto: confirmado que a página monta,
troca de aba funciona, a tira de campanhas mostra tanto atrativos "em
campanha" quanto "sem campanha detectada" com o dado real, e a tela de
evolução expõe os 3 seletores esperados. Não foi tirado um screenshot
pixel a pixel (limitação do ambiente) — se precisar de validação visual
completa, abrir o arquivo publicado no GitHub Pages num navegador normal.

## YupStar Rio: resolução parcial via coleta manual (2026-07-14)

O bloqueio de Cloudflare Turnstile (ver seção acima) permanece sem
solução automatizável, mas os preços em si sempre estiveram visíveis no
HTML estático da página assim que acessada por um navegador real — só a
automação (Playwright/curl) é bloqueada. A pedido do usuário, passou-se a
coletar esses preços manualmente (via sessão do Claude in Chrome, lendo
a página real) e inserir no banco, em vez de deixar o concorrente de fora
do dashboard indefinidamente.

**Processo institucionalizado em `scripts/coletar_yupstar_manual.py`:**
1. Alguém com navegador real abre
   `https://rio.yupstar.com.br/as-rodas/yup-star-rio/` e lê os preços
   exibidos.
2. Atualiza o dicionário `PRECOS_MANUAIS` no script com os valores e mês
   de referência atuais.
3. Roda `python3 scripts/coletar_yupstar_manual.py --mes AAAA-MM` — insere
   os preços na coleta (`id_coleta`) já existente daquele mês (não cria
   coleta nova; YupStar Rio é só mais um concorrente dentro da coleta
   mensal que os outros 5 atrativos automatizados já fizeram). É
   idempotente: rodar de novo no mesmo mês substitui os preços anteriores
   do YupStar Rio sem duplicar linhas.
4. Reexportar o dashboard: `python3 historico/exportar_para_dashboard.py`.

Dados reais coletados em 2026-07 (produto "Yup Star Rio": Adulto R$59,90,
Melhor Idade R$39,90, Infantil R$39,90; produto "Promoção de Julho":
combo 2 ingressos + pipoca ou chopp R$79,90). O produto "Promoção de
Julho" é corretamente sinalizado como campanha promocional pelo próprio
mecanismo de detecção (nome contém "Promoção"); os preços regulares do
produto "Yup Star Rio" não são.

## Dashboard: tabela completa com ranking, cascata e variantes de embarque (2026-07-13)

A aba "Tarifário completo" ganhou, a pedido do usuário:
- **Ranking/ordenação clicável** nas colunas Atrativo (A-Z) e Preço
  (valor), com indicador visual de seta (↑/↓) e estado de ordenação ativa.
- **Cascata de filtros** (Atrativo → Ingresso → Categoria), no mesmo
  padrão já usado na aba "Evolução de preço": selecionar um atrativo
  restringe a lista de ingressos disponíveis, e selecionar um ingresso
  restringe a lista de categorias — os selects dependentes resetam
  automaticamente quando o pai muda.
- **Variantes de embarque visíveis via cascata:** ao selecionar um
  atrativo E um ingresso específico (não "todos"), a tabela passa a
  mostrar todas as linhas (inclusive as com `variante_tipo` preenchido) e
  uma coluna extra "Variante". Isso resolve a lacuna notada pelo usuário
  de que os preços do Paineiras-Corcovado saindo de Largo do Machado e
  Copacabana só apareciam antes na seção separada "Preços com variantes"
  — agora também aparecem diretamente na tabela principal ao filtrar por
  esse ingresso específico.

A aba "Evolução de preço" teve seus 3 seletores (Atrativo/Ingresso/
Categoria) restilizados para o mesmo padrão compacto da aba Tarifário
Completo (selects pequenos, sem `<label>` separado, inline no topo do
cartão do gráfico) — a pedido do usuário, por ter gostado mais desse
estilo do que o cartão "Selecionar ingresso" anterior, que foi removido.

## Riscos operacionais a monitorar

- Toda a lógica Limber Software depende de engenharia reversa não
  documentada oficialmente. Se a plataforma mudar o algoritmo de
  criptografia, adicionar assinatura HMAC nas requisições, ou trocar o
  esquema de autenticação, o coletor quebra e exige nova investigação
  (repetir o processo do PLAYBOOK_INVESTIGACAO.md, Padrão C).
- O parser HTML do Trem do Corcovado é frágil a mudanças de front-end
  (se as classes CSS div.row, h5, span.amount mudarem, quebra
  silenciosamente — retornaria um dicionário de categorias vazio, não um
  erro, então vale conferir a contagem de categorias retornadas a cada
  coleta).
- Filtro de SKU de teste (is_test_sku em limber_scraper.py) usa
  uma lista de padrões de nome (teste, test, homolog, dummy, exemplo).
  Concorrentes novos podem usar outros padrões — vale revisar a lista
  skus_teste_ignorados do output a cada nova região mapeada.
