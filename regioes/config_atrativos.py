"""
Configuracao declarativa de atrativos turisticos monitorados.
================================================================

Este arquivo define CADA ATRATIVO como uma entrada de configuracao, nao como
codigo novo. O objetivo e que adicionar um atrativo em uma regiao nova seja
questao de preencher um dicionario, nao escrever um scraper do zero.

Cada atrativo tem um "mecanismo" (mechanism) que diz ao coletor generico
qual estrategia de coleta usar. Os mecanismos disponiveis hoje (todos
descobertos e validados durante o projeto piloto do Rio de Janeiro):

  - "limber_software": plataforma SaaS de bilheteria "Limber Software".
    Reconhecivel por: URL de compra no formato ingressos.<dominio>.com.br,
    e um endpoint /uploads/ec-config/{host}/PT/config que retorna configuracao
    cifrada. Cobre: Paineiras-Corcovado, AquaRio, BioParque do Rio (RJ).

  - "api_json_aberta": API JSON propria do proprio atrativo, sem autenticacao,
    endpoint descoberto via inspecao de rede (DevTools). Cobre: Bondinho
    Pao de Acucar (RJ).

  - "html_form_post": endpoint que retorna um fragmento HTML (nao JSON) via
    POST simples, sem autenticacao -- tipico de sites ASP.NET MVC mais
    simples. Requer parsing com BeautifulSoup. Cobre: Trem do Corcovado (RJ).

  - "protegido_cloudflare_turnstile": site com Cloudflare Turnstile ativo,
    que bloqueia scraping headless simples. Precos precisam ser coletados
    manualmente ou via navegador real automatizado (nao coberto pelo
    coletor automatico ainda). Cobre: YupStar Rio (RJ).

QUANDO MAPEAR UM ATRATIVO NOVO (de qualquer regiao):
1. Seguir o playbook em scripts/PLAYBOOK_INVESTIGACAO.md para descobrir
   o mecanismo do site (a maioria dos sites de bilheteria vai cair em um
   dos mecanismos ja conhecidos acima).
2. Se for um mecanismo ja conhecido (ex: outro cliente Limber Software em
   outra cidade), basta adicionar uma nova entrada aqui com os dados do
   tenant (hostname, sku dos produtos relevantes).
3. Se for um mecanismo novo, documentar o novo mecanismo seguindo o mesmo
   padrao (endpoint, autenticacao, formato de resposta) e implementar o
   coletor correspondente em scripts/coletores/.
"""

# ---------------------------------------------------------------------------
# Regiao: Rio de Janeiro (projeto piloto)
# ---------------------------------------------------------------------------

RIO_DE_JANEIRO = {
    "regiao": "Rio de Janeiro",
    "atrativos": [
        {
            "nome": "Parque Bondinho Pão de Açúcar",
            "e_proprio": True,  # este e o proprio negocio do usuario, nao concorrente
            "mechanism": "api_json_aberta",
            "config": {
                "endpoint": "https://backend.bondinho.com.br/api/Products/GetProductsRangeFromCategories",
                "metodo": "POST",
                "payload": {"categoryCode": ["CAT-SITEUN91434"], "channel": 2, "lang": "BR"},
                "mapa_campos": {
                    "nome_produto": "productName",
                    "codigo_estavel": "productCode",
                    "preco_adulto": "minPriceAdult",
                    "preco_crianca": "minPriceChild",
                    "preco_idoso": "minPriceElders",
                },
            },
        },
        {
            "nome": "Trem do Corcovado",
            "e_proprio": False,
            "mechanism": "html_form_post",
            "config": {
                "endpoint": "https://www.tremdocorcovado.rio/Home/getTicket",
                "metodo": "POST",
                "headers_extra": {"X-Requested-With": "XMLHttpRequest"},
                "referer": "https://www.tremdocorcovado.rio/",
                "seletor_linha": "div.row",
                "seletor_nome": "h5",
                "seletor_preco": "span.amount",
            },
        },
        {
            "nome": "Paineiras-Corcovado",
            "e_proprio": False,
            "mechanism": "limber_software",
            "config": {
                "hostname": "ingressos.paineirascorcovado.com.br",
                "skus_relevantes": [3073, 4552, 8014],  # avulso + 2 combos
                "particularidades": ["preco_por_local_embarque"],
            },
        },
        {
            "nome": "AquaRio",
            "e_proprio": False,
            "mechanism": "limber_software",
            "config": {
                "hostname": "ingressos.aquariomarinhodorio.com.br",
                "skus_relevantes": None,  # None = coletar todos os SKUs ativos automaticamente
                "particularidades": [],
            },
        },
        {
            "nome": "BioParque do Rio",
            "e_proprio": False,
            "mechanism": "limber_software",
            "config": {
                "hostname": "ingressos.bioparquedorio.com.br",
                "skus_relevantes": None,
                "particularidades": ["preco_por_temporada", "preco_d0_vs_antecipado"],
            },
        },
        {
            "nome": "YupStar Rio",
            "e_proprio": False,
            "mechanism": "protegido_cloudflare_turnstile",
            "config": {
                "url": "https://rio.yupstar.com.br/as-rodas/yup-star-rio/",
                "grupo_controlador": "Gramado Parks",
                "nota": "Precos estao no HTML estatico da pagina, mas o Cloudflare "
                        "Turnstile bloqueia scraping headless simples. Coleta manual "
                        "por enquanto -- ver CONHECIMENTO.md secao 'Casos nao resolvidos'.",
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# Regiao: [preencher ao expandir para nova regiao]
# ---------------------------------------------------------------------------
# Copie o padrao acima. Nomeie a variavel em maiusculas (ex: GRAMADO,
# SAO_PAULO, etc.) e adicione a regiao na lista REGIOES_DISPONIVEIS abaixo.

# GRAMADO = {
#     "regiao": "Gramado, RS",
#     "atrativos": [
#         # ...
#     ],
# }


REGIOES_DISPONIVEIS = {
    "rio_de_janeiro": RIO_DE_JANEIRO,
    # "gramado": GRAMADO,
}
