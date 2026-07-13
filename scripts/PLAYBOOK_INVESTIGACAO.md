# Playbook de Investigação Técnica — Mapeamento de Sites de Bilheteria

Este documento descreve o processo passo a passo para descobrir como extrair
preços de um site de venda de ingressos novo, baseado no que funcionou no
projeto piloto (Rio de Janeiro, 6 atrativos mapeados). Siga esta ordem —
ela vai do caminho mais simples ao mais complexo, e a maioria dos sites
resolve nas primeiras etapas.

## Fase 0: Reconhecimento (sempre primeiro, para qualquer site novo)

1. Abrir o site no Chrome com DevTools → aba **Network**, filtro **Fetch/XHR**.
2. Navegar até a página de compra de ingressos.
3. Observar as chamadas de rede que aparecem. Ignorar ruído óbvio: Google
   Analytics, Meta Pixel, TikTok Pixel, Clarity, DoubleClick, etc.
4. Procurar por uma chamada com nome sugestivo: `products`, `tickets`,
   `sku`, `preco`, `catalog`, `getTicket`, etc.
5. Classificar o que foi encontrado em um dos padrões abaixo.

## Padrão A — API JSON aberta, sem autenticação

**Como identificar:** a chamada de rede retorna JSON legível diretamente,
sem headers de autorização, sem payload cifrado.

**Como validar:** copie a chamada (URL + método + body) e replique com
`curl` ou `requests` puro, fora do navegador. Se retornar os mesmos dados,
confirmado.

**Exemplo real:** Parque Bondinho Pão de Açúcar —
`POST https://backend.bondinho.com.br/api/Products/GetProductsRangeFromCategories`
com body `{"categoryCode": [...], "channel": 2, "lang": "BR"}`, sem nenhum
header de autenticação.

**Complexidade de manutenção:** baixa.

## Padrão B — Resposta HTML (não JSON) via POST simples

**Como identificar:** parecido com o Padrão A, mas a resposta é um
fragmento HTML (ex: uma `partial view` de ASP.NET MVC), não JSON.

**Como validar:** igual ao Padrão A, mas o parsing precisa de
BeautifulSoup (ou similar) em vez de `.json()`.

**Exemplo real:** Trem do Corcovado —
`POST https://www.tremdocorcovado.rio/Home/getTicket`, retorna HTML com
`<div class="row">` por categoria de ingresso, preço em `<span class="amount">`.

**Complexidade de manutenção:** baixa, mas frágil a mudanças de HTML/CSS
do site (se a classe do elemento mudar, o parser quebra).

## Padrão C — Plataforma SaaS de bilheteria com payload cifrado

**Como identificar:** a URL de compra costuma ter um subdomínio dedicado
(ex: `ingressos.<dominio>.com.br`). O rodapé da página frequentemente
exibe o nome da plataforma (ex: "Limber Software — A plataforma de soluções
para o turismo e entretenimento"). As respostas de API são strings cifradas
(formato `"U2FsdGVkX1..."`, que é a assinatura do CryptoJS `Salted__` em
Base64).

**Como resolver (mecanismo Limber Software, documentado em detalhe em
`CONHECIMENTO.md`):**

1. Buscar `GET /uploads/ec-config/{hostname}/PT/config` → decriptar com a
   chave fixa conhecida → extrair `env.cryptoKey` (específico do tenant),
   `geral.token` (JWT bearer) e `geral.idParceiro`.
2. Buscar `GET /api/auth/csrf?xlh={base64(hostname_invertido)}` → usar o
   `csrfToken` do corpo da resposta (não o cookie).
3. Montar headers: `Authorization: Bearer {token}`, `x-xsrf-token:
   {csrfToken}`, `x-l-h: {mesmo xlh do passo 2}`.
4. `POST /api/cross/consulta/allsku` (corpo cifrado com `cryptoKey`) →
   catálogo de produtos.
5. `POST /api/cross/consulta/sku` (corpo cifrado) → detalhe do produto
   (preços, temporadas, locais de embarque).
6. Casos especiais que também usam este mecanismo, mas com payload
   diferente: `POST /api/cross/consulta/configpreco` (preço por local de
   embarque OU preço por data específica, cobrindo sazonalidade e
   antecedência de compra — ver `CONHECIMENTO.md`).

**Se você encontrar um novo tenant Limber Software:** o mecanismo inteiro
já está implementado em `scripts/limber_scraper.py`. Basta adicionar uma
entrada em `regioes/config_atrativos.py` com o `hostname` do novo tenant —
nenhum código novo é necessário, a menos que o novo tenant tenha uma
particularidade de preço ainda não vista (embarque, sazonalidade, etc. — e
mesmo essas já estão cobertas).

**Complexidade de manutenção:** média. Quebra se a Limber Software mudar o
algoritmo de criptografia, adicionar assinatura HMAC, ou mudar o esquema de
autenticação.

## Padrão D — Proteção anti-bot forte (Cloudflare Turnstile e similares)

**Como identificar:** a página carrega uma tela de "verificação de
segurança" com checkbox "Confirme que é humano" antes do conteúdo real.
Isso é diferente do Cloudflare "silencioso" que alguns sites Limber
Software usam (que passa sem interação quando o navegador tem fingerprint
realista) — aqui há um desafio ativo.

**Como testar se é bloqueio real:** tentar Playwright headless. Se travar
na tela de verificação mesmo com `playwright-stealth` aplicado, é Padrão D
confirmado.

**Como resolver (nenhuma solução automática validada ainda):**
- Opção 1: navegador real controlado via extensão (ex: Claude in Chrome),
  não Playwright headless — passa porque tem fingerprint de browser real.
  Ainda exige interação manual por enquanto.
- Opção 2 (não testada): serviço pago de resolução de Turnstile/CAPTCHA
  (2captcha, CapMonster).
- Opção 3: verificar se existe uma API pública do grupo controlador do
  site (ex: um grupo com múltiplas marcas pode ter uma API compartilhada
  sem essa proteção em outro domínio).

**Exemplo real:** YupStar Rio (grupo Gramado Parks). Os preços em si
ficam no HTML estático da página (não há API JSON separada), então uma
vez resolvido o desafio anti-bot, a extração é trivial.

**Complexidade de manutenção:** alta. Considerar coleta manual mensal
para estes casos, a menos que o volume justifique investir em uma solução
paga de bypass.

## Checklist para adicionar um atrativo novo (de qualquer região)

- [ ] Fase 0: abrir DevTools, identificar chamadas de rede reais
- [ ] Classificar em Padrão A, B, C ou D
- [ ] Se A, B ou C: validar a chamada isolada via `curl`/`requests`, sem
      navegador
- [ ] Se C (Limber Software) ou outra plataforma SaaS já mapeada: apenas
      adicionar entrada em `regioes/config_atrativos.py`
- [ ] Se mecanismo genuinamente novo: documentar aqui como um novo
      "Padrão E" e implementar o coletor em `scripts/coletores/`
- [ ] Rodar o coletor e comparar manualmente 2-3 preços contra o que
      aparece no site real (checagem de sanidade obrigatória antes de
      confiar nos dados)
- [ ] Adicionar ao `historico/` para começar a acumular série temporal
