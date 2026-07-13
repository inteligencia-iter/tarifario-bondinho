"""
Coletor consolidado de tarifario dos concorrentes.
=====================================================

Cobre 5 dos 6 sites mapeados sem precisar de navegador (requests puro):
- Parque Bondinho Pao de Acucar (proprio)   -- Cenario A
- Trem do Corcovado                          -- Cenario A (resposta HTML)
- Paineiras-Corcovado                        -- Cenario B+ (Limber Software)
- AquaRio                                    -- Cenario B+ (Limber Software)
- BioParque do Rio                           -- Cenario B+ (Limber Software)

O 6o site, YupStar Rio, usa Cloudflare Turnstile e exige navegador real
(nao headless) -- ver nota no final deste arquivo.

Uso:
    python3 coletor_concorrentes.py > snapshot_YYYY-MM-DD.json
"""
import sys
import json
import re
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from limber_scraper import scrape_site as scrape_limber_site


# ---------------------------------------------------------------------------
# Parque Bondinho Pao de Acucar (proprio)
# ---------------------------------------------------------------------------

def coletar_bondinho():
    r = requests.post(
        "https://backend.bondinho.com.br/api/Products/GetProductsRangeFromCategories",
        json={"categoryCode": ["CAT-SITEUN91434"], "channel": 2, "lang": "BR"},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()["data"]
    produtos = []
    for p in data:
        produtos.append({
            "codigo": p["productCode"],
            "nome": p["productName"],
            "categorias": {
                "Adulto": p.get("minPriceAdult"),
                "Crianca/Promocional": p.get("minPriceChild"),
                "Idoso/Meia/Estudante": p.get("minPriceElders"),
            },
        })
    return {"site": "bondinho.com.br", "produtos": produtos}


# ---------------------------------------------------------------------------
# Trem do Corcovado
# ---------------------------------------------------------------------------

def coletar_trem_corcovado():
    r = requests.post(
        "https://www.tremdocorcovado.rio/Home/getTicket",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.tremdocorcovado.rio/",
        },
        timeout=15,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    categorias = {}
    for row in soup.select("div.row"):
        h5 = row.select_one("h5")
        amount = row.select_one("span.amount")
        if h5 and amount:
            valor_str = amount.text.strip().replace("R$", "").strip()
            valor_str = valor_str.replace(".", "").replace(",", ".")
            try:
                categorias[h5.text.strip()] = float(valor_str)
            except ValueError:
                pass
    return {"site": "tremdocorcovado.rio", "produtos": [{"nome": "Trem do Corcovado", "categorias": categorias}]}


# ---------------------------------------------------------------------------
# Sites Limber Software (Paineiras, AquaRio, BioParque)
# ---------------------------------------------------------------------------

LIMBER_HOSTS = {
    "Paineiras-Corcovado": "ingressos.paineirascorcovado.com.br",
    "AquaRio": "ingressos.aquariomarinhodorio.com.br",
    "BioParque do Rio": "ingressos.bioparquedorio.com.br",
}


def coletar_limber(nome_site: str, hostname: str):
    data = scrape_limber_site(hostname)
    produtos = []
    for p in data["produtos"]:
        entry = {
            "sku": p["sku"],
            "nome": p["nome"],
            "categorias": {c["nome"]: c["valor"] for c in p["categorias"]},
        }
        if p.get("locais_embarque"):
            entry["locais_embarque"] = [le["nome"] for le in p["locais_embarque"]]
        if p.get("precos_por_local_embarque"):
            entry["precos_por_local_embarque"] = {
                local: {c["nome"]: c["valor"] for c in categorias}
                for local, categorias in p["precos_por_local_embarque"].items()
            }
        if p.get("precos_por_temporada"):
            entry["precos_por_temporada"] = {
                temporada: {c["nome"]: c["valor"] for c in categorias}
                for temporada, categorias in p["precos_por_temporada"].items()
            }
        if p.get("precos_por_temporada_por_receita"):
            entry["precos_por_temporada_por_receita"] = {
                receita: {
                    temporada: {c["nome"]: c["valor"] for c in categorias}
                    for temporada, categorias in temporadas.items()
                }
                for receita, temporadas in p["precos_por_temporada_por_receita"].items()
            }
        produtos.append(entry)
    return {"site": hostname, "produtos": produtos}


# ---------------------------------------------------------------------------
# Execucao principal
# ---------------------------------------------------------------------------

def coletar_tudo():
    resultado = {
        "data_coleta": datetime.now(timezone.utc).isoformat(),
        "sites": {},
        "erros": {},
    }

    coletores = [
        ("Parque Bondinho Pão de Açúcar (próprio)", coletar_bondinho),
        ("Trem do Corcovado", coletar_trem_corcovado),
    ]
    for nome, func in coletores:
        try:
            r = func()
            resultado["sites"][nome] = r["produtos"]
            print(f"[OK] {nome}: {len(r['produtos'])} produto(s)", file=sys.stderr)
        except Exception as e:
            resultado["erros"][nome] = str(e)
            print(f"[ERRO] {nome}: {e}", file=sys.stderr)

    for nome_site, hostname in LIMBER_HOSTS.items():
        try:
            r = coletar_limber(nome_site, hostname)
            resultado["sites"][nome_site] = r["produtos"]
            print(f"[OK] {nome_site}: {len(r['produtos'])} produto(s)", file=sys.stderr)
        except Exception as e:
            resultado["erros"][nome_site] = str(e)
            print(f"[ERRO] {nome_site}: {e}", file=sys.stderr)

    print(
        "\n[NOTA] YupStar Rio nao esta incluido -- usa Cloudflare Turnstile e "
        "exige navegador real (nao headless). Ver observacoes no inventario tecnico.",
        file=sys.stderr,
    )
    return resultado


if __name__ == "__main__":
    resultado = coletar_tudo()
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
