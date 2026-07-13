"""
Coleta manual do YupStar Rio (Cloudflare Turnstile bloqueia scraping
automatizado, mas os precos estao no HTML estatico da pagina -- ver
CONHECIMENTO.md, secao "Caso nao resolvido: protecao anti-bot").

Este script NAO acessa a internet sozinho. O processo e:
  1. Alguem (ou uma sessao com navegador real, ex: Claude in Chrome dentro
     do Cowork) abre https://rio.yupstar.com.br/as-rodas/yup-star-rio/ e
     le os precos exibidos na pagina.
  2. Atualiza o dicionario PRECOS_MANUAIS abaixo com os valores e o mes de
     referencia correntes.
  3. Roda este script: ele insere os precos na coleta (id_coleta) ja
     existente do mes de referencia indicado -- NAO cria uma coleta nova,
     porque o YupStar Rio e só mais um concorrente dentro da coleta
     mensal que os outros 5 atrativos ja fizeram via coletor_concorrentes.py.
  4. Reexportar o dashboard: python3 historico/exportar_para_dashboard.py

Uso:
    python3 scripts/coletar_yupstar_manual.py --mes 2026-07

Idempotente: rodar de novo para o mesmo mes substitui os precos anteriores
do YupStar Rio naquele mes (nao duplica linhas).
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "historico"))
from schema import get_connection

CONCORRENTE = "YupStar Rio"

# Atualize estes valores a cada coleta mensal, apos ler a pagina real.
# Fonte: https://rio.yupstar.com.br/as-rodas/yup-star-rio/ (HTML estatico,
# sem API por tras -- ver CONHECIMENTO.md).
PRECOS_MANUAIS = {
    "Yup Star Rio": {
        "produto_id": "Yup Star Rio",
        "categorias": {
            "Adulto": 59.90,
            "Melhor Idade": 39.90,
            "Infantil": 39.90,
        },
    },
    "Promoção de Julho": {
        "produto_id": "Promoção de Julho (Yup Star Rio)",
        "categorias": {
            "Combo 2 ingressos + pipoca ou chopp": 79.90,
        },
    },
}


def obter_id_coleta(conn, mes_referencia: str) -> int:
    row = conn.execute(
        "SELECT id_coleta FROM coletas WHERE mes_referencia = ? ORDER BY id_coleta DESC LIMIT 1",
        (mes_referencia,),
    ).fetchone()
    if row is None:
        raise SystemExit(
            f"Nao existe nenhuma coleta registrada para o mes {mes_referencia}. "
            "Rode coletar_e_registrar.py primeiro (ele cria a coleta com os "
            "outros 5 atrativos automatizados) e só depois este script."
        )
    return row[0]


def inserir_yupstar_manual(mes_referencia: str):
    conn = get_connection()
    id_coleta = obter_id_coleta(conn, mes_referencia)

    # Idempotencia: remove entradas anteriores do YupStar Rio nesta coleta
    # antes de reinserir, para permitir rodar de novo com precos atualizados
    # sem duplicar linhas.
    conn.execute(
        "DELETE FROM precos WHERE id_coleta = ? AND concorrente = ?",
        (id_coleta, CONCORRENTE),
    )

    linhas = 0
    for produto_nome, dados in PRECOS_MANUAIS.items():
        produto_id = dados["produto_id"]
        for categoria, valor in dados["categorias"].items():
            conn.execute(
                """INSERT INTO precos
                   (id_coleta, concorrente, produto_id, produto_nome, categoria, valor,
                    variante_tipo, variante_nome)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)""",
                (id_coleta, CONCORRENTE, produto_id, produto_nome, categoria, valor),
            )
            linhas += 1

    conn.execute(
        """UPDATE coletas SET observacoes = COALESCE(observacoes || ' | ', '') ||
           'YupStar Rio incluido via coleta manual (navegador real, Cloudflare Turnstile '
           'bloqueia scraping automatizado -- ver CONHECIMENTO.md)'
           WHERE id_coleta = ?""",
        (id_coleta,),
    )

    conn.commit()
    conn.close()
    return id_coleta, linhas


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mes", required=True, help="Mes de referencia, formato YYYY-MM (ex: 2026-07)")
    args = parser.parse_args()

    id_coleta, n = inserir_yupstar_manual(args.mes)
    print(f"OK: {n} linha(s) de preco do YupStar Rio inseridas na coleta #{id_coleta} ({args.mes}).")
