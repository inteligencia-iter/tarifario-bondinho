"""
Exporta o banco historico (tarifario.db) para um JSON estatico, que o
dashboard em docs/index.html consome via fetch. Roda como ultimo passo do
workflow do GitHub Actions, depois de coletar_e_registrar.py.

Por que exportar para JSON em vez do dashboard ler o .db diretamente:
GitHub Pages serve apenas arquivos estaticos, e o navegador nao le SQLite
nativamente sem uma dependencia extra (sql.js/WASM), o que adicionaria
complexidade sem necessidade real aqui -- o volume de dados e pequeno
(algumas centenas de KB por ano) e um JSON simples e mais facil de consumir
com fetch() puro, sem dependencias adicionais no frontend.

Uso:
    python3 historico/exportar_para_dashboard.py
"""
import sys
import json
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from schema import get_connection

DOCS_DIR = Path(__file__).parent.parent / "docs"
OUTPUT_PATH = DOCS_DIR / "dados_tarifario.json"


def exportar():
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    coletas = [dict(r) for r in conn.execute(
        "SELECT id_coleta, data_coleta, mes_referencia, observacoes FROM coletas ORDER BY data_coleta"
    )]

    precos = [dict(r) for r in conn.execute("""
        SELECT p.id_coleta, c.mes_referencia, c.data_coleta,
               p.concorrente, p.produto_id, p.produto_nome, p.categoria, p.valor,
               p.variante_tipo, p.variante_nome
        FROM precos p JOIN coletas c ON c.id_coleta = p.id_coleta
        ORDER BY c.data_coleta, p.concorrente, p.produto_nome
    """)]

    conn.close()

    payload = {
        "gerado_em": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "coletas": coletas,
        "precos": precos,
    }

    DOCS_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))  # compacto, sem indentacao

    print(f"Exportado: {len(coletas)} coleta(s), {len(precos)} linha(s) de preco -> {OUTPUT_PATH}")


if __name__ == "__main__":
    exportar()
