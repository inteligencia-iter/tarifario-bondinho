"""
Consultas de analise sobre o historico de tarifario: MoM (Month over Month)
e YoY (Year over Year), alem de visualizacao simples do historico completo
de um produto especifico.

Uso:
    python3 historico/analises.py historico          # ver todo o historico
    python3 historico/analises.py mom                # variacao mes a mes (ultima coleta de cada mes)
    python3 historico/analises.py yoy                 # variacao ano a ano
    python3 historico/analises.py produto <concorrente> <produto_id>
"""
import sys
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "tarifario.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def historico_completo():
    """Lista todas as coletas registradas, uma linha por coleta."""
    conn = get_connection()
    print(f"{'ID':<5} {'Mes ref.':<10} {'Data coleta':<28} {'Qtd precos':<10} Observacoes")
    print("-" * 90)
    for row in conn.execute("""
        SELECT c.id_coleta, c.mes_referencia, c.data_coleta, COUNT(p.id_preco) as n_precos, c.observacoes
        FROM coletas c LEFT JOIN precos p ON p.id_coleta = c.id_coleta
        GROUP BY c.id_coleta ORDER BY c.data_coleta
    """):
        print(f"{row['id_coleta']:<5} {row['mes_referencia']:<10} {row['data_coleta']:<28} "
              f"{row['n_precos']:<10} {row['observacoes'] or ''}")
    conn.close()


def variacao_mom():
    """Compara o preco 'base' (sem variante) de cada produto/categoria entre
    meses de referencia consecutivos, usando a coleta mais recente de cada mes."""
    conn = get_connection()
    query = """
    WITH ultima_coleta_por_mes AS (
        SELECT mes_referencia, MAX(id_coleta) as id_coleta
        FROM coletas GROUP BY mes_referencia
    ),
    precos_mensais AS (
        SELECT u.mes_referencia, p.concorrente, p.produto_id, p.produto_nome, p.categoria, p.valor
        FROM precos p
        JOIN ultima_coleta_por_mes u ON u.id_coleta = p.id_coleta
        WHERE p.variante_tipo IS NULL
    )
    SELECT
        atual.concorrente, atual.produto_nome, atual.categoria,
        anterior.mes_referencia as mes_anterior, anterior.valor as valor_anterior,
        atual.mes_referencia as mes_atual, atual.valor as valor_atual,
        ROUND(atual.valor - anterior.valor, 2) as variacao_absoluta,
        ROUND(100.0 * (atual.valor - anterior.valor) / anterior.valor, 2) as variacao_pct
    FROM precos_mensais atual
    JOIN precos_mensais anterior
        ON anterior.concorrente = atual.concorrente
        AND anterior.produto_id = atual.produto_id
        AND anterior.categoria = atual.categoria
        AND anterior.mes_referencia = (
            SELECT MAX(mes_referencia) FROM precos_mensais p2
            WHERE p2.mes_referencia < atual.mes_referencia
              AND p2.concorrente = atual.concorrente AND p2.produto_id = atual.produto_id
              AND p2.categoria = atual.categoria
        )
    WHERE atual.valor != anterior.valor
    ORDER BY ABS(atual.valor - anterior.valor) DESC
    """
    conn2 = get_connection()
    rows = conn2.execute(query).fetchall()
    if not rows:
        print("Nenhuma variacao MoM detectada (ou historico insuficiente -- precisa de 2+ meses distintos).")
        return
    print(f"{'Concorrente':<25} {'Produto':<35} {'Categoria':<15} {'Mes ant.':<9} {'R$ ant.':<9} "
          f"{'Mes atual':<10} {'R$ atual':<9} {'Δ R$':<8} {'Δ %'}")
    print("-" * 140)
    for r in rows:
        print(f"{r['concorrente']:<25} {r['produto_nome'][:33]:<35} {r['categoria'][:13]:<15} "
              f"{r['mes_anterior']:<9} {r['valor_anterior']:<9} {r['mes_atual']:<10} {r['valor_atual']:<9} "
              f"{r['variacao_absoluta']:<8} {r['variacao_pct']}%")
    conn.close()


def variacao_yoy():
    """Compara o mesmo mes de referencia entre anos diferentes (ex: 2026-07 vs 2027-07)."""
    conn = get_connection()
    query = """
    WITH ultima_coleta_por_mes AS (
        SELECT mes_referencia, MAX(id_coleta) as id_coleta
        FROM coletas GROUP BY mes_referencia
    ),
    precos_mensais AS (
        SELECT u.mes_referencia, p.concorrente, p.produto_id, p.produto_nome, p.categoria, p.valor
        FROM precos p
        JOIN ultima_coleta_por_mes u ON u.id_coleta = p.id_coleta
        WHERE p.variante_tipo IS NULL
    )
    SELECT
        atual.concorrente, atual.produto_nome, atual.categoria,
        anterior.mes_referencia as mes_ano_anterior, anterior.valor as valor_ano_anterior,
        atual.mes_referencia as mes_atual, atual.valor as valor_atual,
        ROUND(atual.valor - anterior.valor, 2) as variacao_absoluta,
        ROUND(100.0 * (atual.valor - anterior.valor) / anterior.valor, 2) as variacao_pct
    FROM precos_mensais atual
    JOIN precos_mensais anterior
        ON anterior.concorrente = atual.concorrente
        AND anterior.produto_id = atual.produto_id
        AND anterior.categoria = atual.categoria
        AND substr(anterior.mes_referencia, 6, 2) = substr(atual.mes_referencia, 6, 2)
        AND CAST(substr(anterior.mes_referencia, 1, 4) AS INTEGER) = CAST(substr(atual.mes_referencia, 1, 4) AS INTEGER) - 1
    ORDER BY atual.mes_referencia, ABS(atual.valor - anterior.valor) DESC
    """
    rows = conn.execute(query).fetchall()
    if not rows:
        print("Nenhuma comparacao YoY disponivel ainda (precisa do mesmo mes em 2 anos diferentes).")
        return
    print(f"{'Concorrente':<25} {'Produto':<35} {'Categoria':<15} {'Ano ant.':<10} {'R$ ant.':<9} "
          f"{'Ano atual':<10} {'R$ atual':<9} {'Δ R$':<8} {'Δ %'}")
    print("-" * 140)
    for r in rows:
        print(f"{r['concorrente']:<25} {r['produto_nome'][:33]:<35} {r['categoria'][:13]:<15} "
              f"{r['mes_ano_anterior']:<10} {r['valor_ano_anterior']:<9} {r['mes_atual']:<10} "
              f"{r['valor_atual']:<9} {r['variacao_absoluta']:<8} {r['variacao_pct']}%")
    conn.close()


def historico_produto(concorrente: str, produto_id: str):
    """Mostra toda a serie historica de um produto especifico (todas as categorias e variantes)."""
    conn = get_connection()
    query = """
    SELECT c.mes_referencia, c.data_coleta, p.categoria, p.valor, p.variante_tipo, p.variante_nome
    FROM precos p JOIN coletas c ON c.id_coleta = p.id_coleta
    WHERE p.concorrente = ? AND p.produto_id = ?
    ORDER BY c.data_coleta, p.categoria, p.variante_nome
    """
    rows = conn.execute(query, (concorrente, produto_id)).fetchall()
    if not rows:
        print(f"Nenhum registro encontrado para concorrente='{concorrente}', produto_id='{produto_id}'.")
        return
    print(f"{'Mes ref.':<10} {'Categoria':<15} {'Valor':<9} {'Variante':<40}")
    print("-" * 80)
    for r in rows:
        variante = f"{r['variante_tipo']}: {r['variante_nome']}" if r['variante_tipo'] else "(preco unico)"
        print(f"{r['mes_referencia']:<10} {r['categoria']:<15} {r['valor']:<9} {variante:<40}")
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    comando = sys.argv[1]
    if comando == "historico":
        historico_completo()
    elif comando == "mom":
        variacao_mom()
    elif comando == "yoy":
        variacao_yoy()
    elif comando == "produto":
        if len(sys.argv) < 4:
            print("Uso: python3 analises.py produto <concorrente> <produto_id>")
            sys.exit(1)
        historico_produto(sys.argv[2], sys.argv[3])
    else:
        print(f"Comando desconhecido: {comando}")
        print(__doc__)
