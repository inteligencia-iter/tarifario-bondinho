"""
Insere um snapshot de coleta (gerado por coletor_concorrentes.py) no banco
historico, no formato longo definido em schema.py.

Uso:
    python3 coletor_concorrentes.py > /tmp/snap.json
    python3 historico/inserir_snapshot.py /tmp/snap.json

    # ou diretamente, coletando e inserindo em um so passo:
    python3 historico/coletar_e_registrar.py
"""
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from schema import get_connection, init_db


def inserir_snapshot(snapshot: dict, mes_referencia: str = None, observacoes: str = None):
    """Insere um snapshot completo (dict retornado por coletor_concorrentes.coletar_tudo())
    no banco historico. Retorna o id_coleta criado."""
    data_coleta = snapshot.get("data_coleta") or datetime.now(timezone.utc).isoformat()
    if mes_referencia is None:
        # Deriva o mes de referencia da data de coleta (ex: '2026-07-11...' -> '2026-07')
        mes_referencia = data_coleta[:7]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO coletas (data_coleta, mes_referencia, observacoes) VALUES (?, ?, ?)",
        (data_coleta, mes_referencia, observacoes),
    )
    id_coleta = cur.lastrowid

    linhas_inseridas = 0
    for concorrente, produtos in snapshot.get("sites", {}).items():
        for produto in produtos:
            produto_id = str(produto.get("sku") or produto.get("codigo") or produto["nome"])
            produto_nome = produto["nome"]

            # 1. Preco unico (sem variante) -- sempre presente como baseline
            for categoria, valor in produto.get("categorias", {}).items():
                cur.execute(
                    """INSERT OR IGNORE INTO precos
                       (id_coleta, concorrente, produto_id, produto_nome, categoria, valor,
                        variante_tipo, variante_nome)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)""",
                    (id_coleta, concorrente, produto_id, produto_nome, categoria, valor),
                )
                linhas_inseridas += cur.rowcount

            # 2. Preco por local de embarque (Paineiras-Corcovado)
            for local, categorias in produto.get("precos_por_local_embarque", {}).items():
                for categoria, valor in categorias.items():
                    cur.execute(
                        """INSERT OR IGNORE INTO precos
                           (id_coleta, concorrente, produto_id, produto_nome, categoria, valor,
                            variante_tipo, variante_nome)
                           VALUES (?, ?, ?, ?, ?, ?, 'embarque', ?)""",
                        (id_coleta, concorrente, produto_id, produto_nome, categoria, valor, local),
                    )
                    linhas_inseridas += cur.rowcount

            # 3. Preco por temporada (BioParque do Rio e derivados) -- caso simples (1 receita)
            for temporada, categorias in produto.get("precos_por_temporada", {}).items():
                for categoria, valor in categorias.items():
                    cur.execute(
                        """INSERT OR IGNORE INTO precos
                           (id_coleta, concorrente, produto_id, produto_nome, categoria, valor,
                            variante_tipo, variante_nome)
                           VALUES (?, ?, ?, ?, ?, ?, 'temporada', ?)""",
                        (id_coleta, concorrente, produto_id, produto_nome, categoria, valor, temporada),
                    )
                    linhas_inseridas += cur.rowcount

            # 3b. Preco por temporada -- caso com multiplas receitas (combos com 2+ atracoes)
            for receita, temporadas in produto.get("precos_por_temporada_por_receita", {}).items():
                for temporada, categorias in temporadas.items():
                    variante_nome = f"{receita} / {temporada}"
                    for categoria, valor in categorias.items():
                        cur.execute(
                            """INSERT OR IGNORE INTO precos
                               (id_coleta, concorrente, produto_id, produto_nome, categoria, valor,
                                variante_tipo, variante_nome)
                               VALUES (?, ?, ?, ?, ?, ?, 'temporada', ?)""",
                            (id_coleta, concorrente, produto_id, produto_nome, categoria, valor, variante_nome),
                        )
                        linhas_inseridas += cur.rowcount

    conn.commit()
    conn.close()
    return id_coleta, linhas_inseridas


if __name__ == "__main__":
    init_db()
    if len(sys.argv) < 2:
        print("Uso: python3 inserir_snapshot.py <arquivo_snapshot.json> [mes_referencia]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        snapshot = json.load(f)

    mes_ref = sys.argv[2] if len(sys.argv) > 2 else None
    id_coleta, n_linhas = inserir_snapshot(snapshot, mes_referencia=mes_ref)
    print(f"Coleta #{id_coleta} inserida com sucesso: {n_linhas} linhas de preco.")
