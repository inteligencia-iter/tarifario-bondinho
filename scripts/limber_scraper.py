"""
Limber Software Scraper
========================
Extrai catalogo de produtos e precos de sites que rodam a plataforma
Limber Software (confirmado em: Paineiras-Corcovado, AquaRio, BioParque do Rio).

Mecanismo (descoberto via engenharia reversa do bundle JS):
1. GET /uploads/ec-config/{host}/PT/config
   -> decripta com chave fixa CONFIG_KEY
   -> extrai env.cryptoKey (por tenant) e geral.token (bearer JWT) e geral.idParceiro
2. GET /api/auth/csrf?xlh={base64(host_invertido)}
   -> retorna {csrfToken: "..."} no BODY (usar esse valor, nao o cookie)
3. POST /api/cross/consulta/allsku
   body = AES_encrypt(JSON.stringify({idparceiro}), cryptoKey)
   headers: Authorization: Bearer {token}, x-xsrf-token: {csrfToken}, x-l-h: {xlh}
   -> resposta cifrada com cryptoKey -> decriptar -> lista de produtos (sem preco)
4. POST /api/cross/consulta/sku
   body = AES_encrypt(JSON.stringify({sku, idparceiro}), cryptoKey)
   mesmos headers
   -> resposta cifrada -> decriptar -> produto completo com 'categorias' (precos)

Uso:
    python3 limber_scraper.py <hostname>
    python3 limber_scraper.py ingressos.aquariomarinhodorio.com.br
"""
import sys
import json
import re
from datetime import datetime, timezone, timedelta
import requests
import urllib3

from decrypt_limber import decrypt_cryptojs, encrypt_cryptojs, host_signature

urllib3.disable_warnings()

CONFIG_KEY = "ecck-SV6QdGk1NCg1NaXzQ"  # chave fixa, usada apenas para /uploads/ec-config
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Padroes de nome que indicam SKU de teste/interno, nao um produto real a venda.
# Ajuste esta lista conforme encontrar outros padroes nos concorrentes monitorados.
TEST_SKU_PATTERNS = [
    r"\bteste\b", r"\btest\b", r"\bhomolog", r"\bdummy\b", r"\bexemplo\b",
]
_TEST_RE = re.compile("|".join(TEST_SKU_PATTERNS), re.IGNORECASE)


def is_test_sku(nome: str) -> bool:
    return bool(_TEST_RE.search(nome or ""))


# ---------- Cliente da plataforma ----------

class LimberClient:
    def __init__(self, hostname: str):
        self.hostname = hostname
        self.api_base = f"https://{hostname}/api"
        self.xlh = host_signature(hostname)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR"})
        self.crypto_key = None
        self.bearer_token = None
        self.id_parceiro = None
        self.config = None

    def load_config(self):
        url = f"https://{self.hostname}/uploads/ec-config/{self.hostname}/PT/config"
        r = self.session.get(url, timeout=15, verify=False)
        r.raise_for_status()
        self.config = json.loads(decrypt_cryptojs(r.text, CONFIG_KEY))
        self.crypto_key = self.config["env"]["cryptoKey"]
        self.bearer_token = self.config["geral"]["token"]
        self.id_parceiro = self.config["geral"]["idParceiro"]
        return self.config

    def authenticate(self):
        r = self.session.get(f"{self.api_base}/auth/csrf", params={"xlh": self.xlh},
                              timeout=15, verify=False)
        r.raise_for_status()
        csrf_token = r.json()["csrfToken"]
        self.session.headers.update({
            "Content-Type": "text/plain",
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {self.bearer_token}",
            "x-xsrf-token": csrf_token,
            "x-l-h": self.xlh,
        })

    def _post_encrypted(self, path: str, payload: dict):
        body = encrypt_cryptojs(json.dumps(payload), self.crypto_key)
        r = self.session.post(f"{self.api_base}{path}", data=body, timeout=20, verify=False)
        r.raise_for_status()
        return json.loads(decrypt_cryptojs(r.text, self.crypto_key))

    def get_all_sku(self):
        return self._post_encrypted("/cross/consulta/allsku", {"idparceiro": self.id_parceiro})

    def get_sku_detail(self, sku: int):
        result = self._post_encrypted("/cross/consulta/sku", {"sku": sku, "idparceiro": self.id_parceiro})
        return result[0] if isinstance(result, list) else result

    def get_calendar(self, sku: int, data_inicial: str, data_final: str, receita: int = None):
        """Retorna disponibilidade + nome da temporada vigente por dia (sem preco).
        data_inicial/data_final no formato YYYY-MM-DD."""
        payload = {
            "dataInicial": data_inicial,
            "dataFinal": data_final,
            "sku": sku,
            "idParceiro": self.id_parceiro,
            "meioVenda": "WEB",
            "localEmbarque": None,
            "quantidade": None,
            "temporada": None,
            "receita": receita,
        }
        return self._post_encrypted("/cross/consulta/disponibilidade/calendario", payload)

    def get_price_by_embarque(self, sku: int, local_embarque: int, data: str, receita: int = None):
        """Retorna o preco por categoria para um local de embarque especifico.
        Alguns produtos cobram valores diferentes dependendo do ponto de embarque
        (ex: Paineiras-Corcovado cobra mais caro para embarques em Copacabana/Largo do Machado
        do que para embarque direto em Paineiras).
        data no formato YYYY-MM-DD. Retorna a lista de categorias com valorUnitario."""
        payload = {
            "idParceiro": self.id_parceiro,
            "data": data,
            "dataFim": data,
            "sku": sku,
            "receita": receita,
            "localEmbarque": local_embarque,
            "meioVenda": "WEB",
        }
        result = self._post_encrypted("/cross/consulta/configpreco", payload)
        item = result[0] if isinstance(result, list) else result
        return item.get("configPreco", {}).get("categorias", [])

    def get_price_by_date(self, sku: int, data: str, receita: int = None):
        """Retorna o preco por categoria para uma data de visita especifica.
        Usa o mesmo endpoint que get_price_by_embarque, mas sem localEmbarque
        (para produtos como BioParque do Rio, que nao tem embarque mas tem
        preco variavel por temporada -- alta/baixa -- e por antecedencia de compra,
        D0=mesmo dia sendo mais caro que D+1 em diante).
        data no formato YYYY-MM-DD."""
        payload = {
            "idParceiro": self.id_parceiro,
            "data": data,
            "dataFim": data,
            "sku": sku,
            "receita": receita,
            "localEmbarque": None,
            "meioVenda": "WEB",
        }
        result = self._post_encrypted("/cross/consulta/configpreco", payload)
        item = result[0] if isinstance(result, list) else result
        return item.get("configPreco", {}).get("categorias", [])


def scrape_site(hostname: str, only_active=True, skip_test_skus=True, include_calendar=False):
    client = LimberClient(hostname)
    client.load_config()
    client.authenticate()

    catalog = client.get_all_sku()
    results = []
    skipped_test = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for item in catalog:
        sku = item["sku"]
        nome = item.get("nome", "")

        if skip_test_skus and is_test_sku(nome):
            skipped_test.append({"sku": sku, "nome": nome})
            continue

        try:
            detail = client.get_sku_detail(sku)
        except Exception as e:
            print(f"  [AVISO] Falha ao buscar SKU {sku} ({nome}): {e}", file=sys.stderr)
            continue

        if only_active and detail.get("ativo") != "S":
            continue

        locais_embarque = detail.get("locaisEmbarque") or []
        temporadas = detail.get("temporadas", []) or []
        entry = {
            "sku": sku,
            "nome": detail.get("nome"),
            "categorias": [
                {"nome": c["nomeCategoria"], "valor": c["valorUnitario"]}
                for c in detail.get("categorias", [])
            ],
            "temporadas_configuradas": [
                {"id": t.get("temporada"), "nome": t.get("nome"), "tipo_receita": t.get("tipoReceita")}
                for t in temporadas
            ],
            "locais_embarque": [
                {
                    "id": le.get("localEmbarque"),
                    "nome": le.get("nomeLocalEmbarque"),
                    "como_chegar": le.get("descricao"),
                }
                for le in locais_embarque
            ],
        }

        # Se o produto tem mais de 1 local de embarque, o preco pode variar por embarque.
        # Busca o preco especifico de cada local e anexa, para nao assumir que 'categorias' vale para todos.
        if len(locais_embarque) > 1:
            receitas_encontradas = sorted(set(
                t.get("tipoReceita") for t in temporadas if t.get("tipoReceita") is not None
            ))
            if len(receitas_encontradas) > 1:
                print(
                    f"  [AVISO] SKU {sku} tem locais de embarque E multiplas receitas "
                    f"({receitas_encontradas}) -- usando a primeira ({receitas_encontradas[0]}), "
                    f"revisar manualmente se o preco parecer errado.",
                    file=sys.stderr,
                )
            receita_ref = receitas_encontradas[0] if receitas_encontradas else None
            data_consulta = today  # usa a data corrente como referencia de preco vigente
            precos_por_embarque = {}
            for le in locais_embarque:
                local_id = le.get("localEmbarque")
                nome_local = le.get("nomeLocalEmbarque")
                try:
                    categorias_local = client.get_price_by_embarque(sku, local_id, data_consulta, receita_ref)
                    precos_por_embarque[nome_local] = [
                        {"nome": c["nomeCategoria"], "valor": c["valorUnitario"]}
                        for c in categorias_local
                    ]
                except Exception as e:
                    print(f"  [AVISO] Falha ao buscar preco do embarque '{nome_local}' (SKU {sku}): {e}", file=sys.stderr)
            if precos_por_embarque:
                entry["precos_por_local_embarque"] = precos_por_embarque

        # Deteccao de sazonalidade (temporadas com nome contendo 'alta'/'baixa'):
        # busca o calendario dos proximos ~45 dias, identifica um dia representativo
        # de cada temporada distinta (incluindo hoje, para capturar preco D0 quando aplicavel),
        # e coleta o preco de cada uma via configpreco. Isso cobre tanto variacao
        # sazonal (ex: fim de semana vs dia de semana) quanto D0 vs D+1.
        #
        # ATENCAO: um produto (ex: combo com 2+ atracoes) pode ter mais de um conjunto de
        # temporadas, uma por 'tipoReceita' (uma por atracao do combo). Cada tipoReceita
        # e tratado separadamente, buscando o calendario e o preco com aquela receita especifica.
        nomes_temporada = [t.get("nome", "") for t in temporadas]
        tem_sazonalidade = any(
            re.search(r"alta|baixa", n, re.IGNORECASE) for n in nomes_temporada
        )
        if tem_sazonalidade:
            receitas_distintas = sorted(set(
                t.get("tipoReceita") for t in temporadas if t.get("tipoReceita") is not None
            ))
            data_fim_busca = (datetime.now(timezone.utc) + timedelta(days=45)).strftime("%Y-%m-%d")
            precos_por_temporada_por_receita = {}

            for receita_ref in receitas_distintas:
                temporadas_desta_receita = [t for t in temporadas if t.get("tipoReceita") == receita_ref]
                nomes_desta_receita = [t.get("nome", "") for t in temporadas_desta_receita]
                if not any(re.search(r"alta|baixa", n, re.IGNORECASE) for n in nomes_desta_receita):
                    continue  # essa receita nao tem sazonalidade por alta/baixa

                try:
                    cal = client.get_calendar(sku, today, data_fim_busca, receita=receita_ref)
                except Exception as e:
                    cal = []
                    print(f"  [AVISO] Falha ao buscar calendario (receita {receita_ref}) do SKU {sku}: {e}", file=sys.stderr)

                dias_por_temporada = {}
                for d in cal:
                    nome_temp = d.get("nomeTemporada")
                    data_str = d["data"][:10]
                    if not nome_temp:
                        continue
                    # So considera esta ocorrencia se o NOME DESTA TEMPORADA especifica
                    # (nao so alguma outra temporada da mesma receita) contiver "alta" ou
                    # "baixa" -- caso contrario e uma temporada sem variacao de preco real
                    # (ex: um nome de local de embarque reaproveitado como nome de
                    # temporada no sistema, como visto no Cristo Redentor via Paineiras).
                    if not re.search(r"alta|baixa", nome_temp, re.IGNORECASE):
                        continue
                    if nome_temp not in dias_por_temporada:
                        dias_por_temporada[nome_temp] = data_str
                    elif dias_por_temporada[nome_temp] == today and data_str != today:
                        # O primeiro dia visto pra essa temporada foi hoje (D0), mas D0 e
                        # coletado separadamente com sua propria logica de preco. Precisamos
                        # de um dia different de "hoje" pra representar o preco normal
                        # dessa temporada (sem a eventual majoracao de D0).
                        dias_por_temporada[nome_temp] = data_str

                precos_desta_receita = {}
                try:
                    categorias_hoje = client.get_price_by_date(sku, today, receita_ref)
                    if not categorias_hoje:
                        # Essa receita nao retorna preco via configpreco (provavelmente usa
                        # outro mecanismo, como o preco estatico de 'categorias'). Pula.
                        continue
                    precos_desta_receita[f"D0 (hoje, {today})"] = [
                        {"nome": c["nomeCategoria"], "valor": c["valorUnitario"]}
                        for c in categorias_hoje
                    ]
                except Exception as e:
                    # 400 aqui costuma indicar que o produto nao vende mais para essa data
                    # (ex: promocoes de data fixa como 'Dia dos Professores' fora do periodo).
                    print(f"  [INFO] SKU {sku} nao tem preco disponivel via configpreco para D0 (receita {receita_ref}): {e}", file=sys.stderr)
                    continue

                for nome_temp, data_rep in dias_por_temporada.items():
                    if data_rep == today:
                        continue
                    try:
                        categorias_temp = client.get_price_by_date(sku, data_rep, receita_ref)
                        label = f"{nome_temp} (ex: {data_rep})"
                        precos_desta_receita[label] = [
                            {"nome": c["nomeCategoria"], "valor": c["valorUnitario"]}
                            for c in categorias_temp
                        ]
                    except Exception as e:
                        print(f"  [AVISO] Falha ao buscar preco '{nome_temp}' (receita {receita_ref}, SKU {sku}): {e}", file=sys.stderr)

                # So vale a pena reportar como "variantes" se pelo menos uma categoria
                # tiver valor numerico diferente entre as variantes coletadas -- caso
                # contrario (ex: uma temporada "Baixa" configurada no sistema mas nunca
                # com preco diferente do normal, como visto no Cristo Redentor, ou um
                # produto com uma unica variante coletada e nada para comparar) isso e
                # apenas ruido: preco unico com nomes de variante que nao significam nada.
                valores_por_categoria = {}
                for categorias in precos_desta_receita.values():
                    for c in categorias:
                        valores_por_categoria.setdefault(c["nome"], set()).add(c["valor"])
                ha_divergencia_real = any(len(vs) > 1 for vs in valores_por_categoria.values())
                if len(precos_desta_receita) <= 1 or not ha_divergencia_real:
                    continue  # nada para comparar, ou tudo igual -- descarta

                if precos_desta_receita:
                    # Nome de referencia da receita (pega o nome de uma das temporadas, sem o Alta/Baixa)
                    nome_receita_ref = temporadas_desta_receita[0].get("nome", str(receita_ref))
                    precos_por_temporada_por_receita[f"receita_{receita_ref} ({nome_receita_ref})"] = precos_desta_receita

            if precos_por_temporada_por_receita:
                if len(precos_por_temporada_por_receita) == 1:
                    # Caso simples: 1 receita so, nao precisa aninhar por receita
                    entry["precos_por_temporada"] = list(precos_por_temporada_por_receita.values())[0]
                else:
                    entry["precos_por_temporada_por_receita"] = precos_por_temporada_por_receita

        if include_calendar and detail.get("controlaHorarios") is not None:
            # Busca so o mes corrente para identificar a temporada vigente hoje.
            month_start = today[:8] + "01"
            try:
                cal = client.get_calendar(sku, month_start, today)
                if cal:
                    ultimo = cal[-1]
                    entry["temporada_vigente"] = ultimo.get("nomeTemporada")
            except Exception as e:
                print(f"  [AVISO] Falha ao buscar calendario do SKU {sku}: {e}", file=sys.stderr)

        results.append(entry)

    return {
        "hostname": hostname,
        "nome_empresa": client.config["geral"]["nomeEmpresa"],
        "coletado_em": datetime.now(timezone.utc).isoformat(),
        "produtos": results,
        "skus_teste_ignorados": skipped_test,
    }


if __name__ == "__main__":
    hostname = sys.argv[1]
    include_calendar = "--calendar" in sys.argv
    data = scrape_site(hostname, include_calendar=include_calendar)
    print(json.dumps(data, indent=2, ensure_ascii=False))
