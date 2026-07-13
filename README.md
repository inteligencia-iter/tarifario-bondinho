# Monitor de Tarifário de Atrativos Turísticos

Projeto de coleta automatizada e histórico de preços de ingressos de
atrativos turísticos concorrentes (e do próprio negócio), para análise
de posicionamento competitivo, sazonalidade, e séries temporais MoM/YoY.

**Origem:** projeto piloto na região do Rio de Janeiro (Grupo Iter /
Parque Bondinho Pão de Açúcar), com 6 atrativos mapeados. Desenhado desde
o início para ser expansível a qualquer outra região.

## Por onde começar

1. **Se você está retomando este projeto depois de um tempo, ou é a
   primeira vez que olha para ele:** leia `CONHECIMENTO.md` primeiro. Ele
   documenta tudo que foi descoberto tecnicamente (como cada site
   funciona por baixo dos panos, os endpoints, as particularidades de
   preço) sem exigir reler o histórico da conversa que originou o
   projeto.

2. **Se você quer adicionar um atrativo/região nova:** leia
   `scripts/PLAYBOOK_INVESTIGACAO.md`. Ele descreve o passo a passo de
   investigação técnica, do caso mais simples ao mais complexo, com
   exemplos reais de cada padrão já encontrado.

3. **Se você só quer rodar a coleta mensal:** veja "Uso mensal" abaixo.

## Estrutura do projeto

```
projeto_tarifario/
├── README.md                         # este arquivo
├── CONHECIMENTO.md                   # conhecimento tecnico consolidado (leitura obrigatoria)
├── requirements.txt                  # dependencias Python (requests, bs4, pycryptodome)
├── .github/workflows/
│   └── coleta_mensal.yml             # agendamento mensal + execucao manual via GitHub Actions
├── docs/                             # servido pelo GitHub Pages
│   ├── index.html                    # dashboard (React CDN + Recharts + Tailwind, sem build)
│   └── dados_tarifario.json          # dado exportado do banco, consumido pelo dashboard
├── regioes/
│   ├── config_atrativos.py           # configuracao declarativa: 1 entrada por atrativo
│   └── inventario_tecnico_*.json     # export legivel da config (gerado, nao editar a mao)
├── scripts/
│   ├── PLAYBOOK_INVESTIGACAO.md      # como mapear um site novo
│   ├── decrypt_limber.py             # utilitario de cripto (AES/CryptoJS) -- fonte unica, sem duplicacao
│   ├── limber_scraper.py             # coletor generico p/ plataforma Limber Software
│   └── coletor_concorrentes.py       # orquestra a coleta de todos os atrativos de uma regiao
└── historico/
    ├── schema.py                     # schema do banco SQLite
    ├── inserir_snapshot.py           # insere um snapshot coletado no banco
    ├── coletar_e_registrar.py        # script principal: coleta + registra, tudo em 1 passo
    ├── exportar_para_dashboard.py    # exporta o banco para docs/dados_tarifario.json
    ├── analises.py                   # consultas prontas: historico, MoM, YoY, serie de 1 produto
    ├── tarifario.db                  # banco de dados (fonte de verdade do historico)
    └── snapshots_brutos/             # backup dos JSONs brutos de cada coleta, por data/hora
```

## Publicando no GitHub Pages

1. No repositório, vá em Settings → Pages → Source, selecione a branch
   principal e a pasta `/docs`.
2. O dashboard fica disponível em `https://<seu-usuario>.github.io/<repo>/`.
3. O workflow `.github/workflows/coleta_mensal.yml` já inclui um passo
   que exporta o banco para `docs/dados_tarifario.json` e commita de volta
   — não é necessário rodar isso manualmente depois de configurado.

## Agendamento e execução manual via GitHub Actions

O workflow roda automaticamente todo dia 1 do mês (09:00 UTC). Para rodar
manualmente: na aba **Actions** do repositório, selecione o workflow
"Coleta mensal de tarifário" → **Run workflow**. Há duas opções
disponíveis nesse disparo manual:
- **forçar**: permite uma 2ª coleta no mesmo mês (útil se a coleta
  agendada falhou parcialmente).
- **mês de referência**: força um mês específico em vez do mês atual
  (útil para coleta atrasada).

O workflow tem permissão de escrita no repositório (`contents: write`)
para poder commitar o banco atualizado (`historico/tarifario.db`) e os
snapshots brutos de volta automaticamente após cada coleta bem-sucedida.


## Uso mensal

```bash
cd historico
python3 coletar_e_registrar.py
```

Isso coleta todos os atrativos configurados, salva um snapshot bruto em
`snapshots_brutos/`, e registra os preços no banco `tarifario.db`. O mês
de referência é derivado automaticamente da data de execução (ex: rodar
em agosto gera `mes_referencia = '2026-08'`). Para forçar um mês
específico (ex: coleta atrasada): `python3 coletar_e_registrar.py --mes 2026-08`.

**Proteção contra duplicação:** se já existe uma coleta registrada para o
mês de referência corrente, o script aborta com um aviso claro em vez de
duplicar silenciosamente. Se você realmente precisa rodar uma segunda vez
no mesmo mês (ex: a primeira coleta falhou parcialmente), use
`python3 coletar_e_registrar.py --forcar`.

Depois de rodar, ver as análises:

```bash
python3 analises.py historico              # lista todas as coletas ja feitas
python3 analises.py mom                    # variacao mes a mes (ultima coleta de cada mes)
python3 analises.py yoy                    # variacao ano a ano (mesmo mes, anos diferentes)
python3 analises.py produto "BioParque do Rio" "8413"   # serie completa de 1 produto
```

## Expandindo para uma região nova

1. Siga `scripts/PLAYBOOK_INVESTIGACAO.md` para descobrir o mecanismo de
   cada atrativo da nova região.
2. Adicione uma nova entrada em `regioes/config_atrativos.py` (copie o
   padrão de `RIO_DE_JANEIRO`).
3. Se o mecanismo já é conhecido (API JSON aberta, HTML via POST, ou
   Limber Software), nenhum código novo é necessário — os coletores
   genéricos em `scripts/` já cobrem esses casos.
4. Se for um mecanismo novo, documente-o no playbook como um novo
   "Padrão" e implemente o coletor correspondente.
5. Rode `coletar_e_registrar.py` e faça uma checagem de sanidade manual
   (compare 2-3 preços contra o site real) antes de confiar na série
   histórica que vai se acumular a partir dali.

## Status atual (última atualização: julho de 2026)

- ✅ 5 de 6 atrativos do Rio de Janeiro totalmente automatizados
- ⚠️ YupStar Rio (RJ) não está automatizado — proteção Cloudflare
  Turnstile não superada ainda (ver `CONHECIMENTO.md`, seção "Caso não
  resolvido")
- ✅ Histórico com 1 mês de dados reais (julho/2026, m0)
- 🔜 Nenhuma região além do Rio de Janeiro mapeada ainda
