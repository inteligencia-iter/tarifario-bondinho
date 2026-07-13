"""
Schema do banco de historico de tarifario dos concorrentes.
=============================================================

Desenhado para permitir analises MoM (mes a mes) e YoY (ano a ano),
preservando as dimensoes especiais descobertas em cada site:
- Paineiras-Corcovado: preco varia por local de embarque
- BioParque do Rio: preco varia por temporada (alta/baixa) e por
  antecedencia de compra (D0 = mesmo dia, mais caro)

Modelo: uma tabela unica 'precos' em formato longo (uma linha por
combinacao concorrente + produto + categoria + variante + data de coleta).
Formato longo facilita agregacoes e evita duplicar colunas quando um novo
tipo de variante aparecer no futuro.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "tarifario.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS coletas (
    id_coleta INTEGER PRIMARY KEY AUTOINCREMENT,
    data_coleta TEXT NOT NULL,          -- ISO 8601, timestamp exato da coleta
    mes_referencia TEXT NOT NULL,       -- 'YYYY-MM', o "m0/m1/m2..." do usuario
    observacoes TEXT
);

CREATE TABLE IF NOT EXISTS precos (
    id_preco INTEGER PRIMARY KEY AUTOINCREMENT,
    id_coleta INTEGER NOT NULL REFERENCES coletas(id_coleta),
    concorrente TEXT NOT NULL,          -- ex: 'BioParque do Rio'
    produto_id TEXT NOT NULL,           -- SKU ou codigo estavel do produto
    produto_nome TEXT NOT NULL,
    categoria TEXT NOT NULL,            -- ex: 'Adulto', 'Meia Entrada'
    valor REAL NOT NULL,

    -- Dimensoes opcionais (NULL quando nao se aplicam ao produto):
    variante_tipo TEXT,                 -- 'embarque' | 'temporada' | NULL (preco unico)
    variante_nome TEXT,                 -- ex: 'Copacabana', 'Alta - Antecipada (ex: 2026-07-12)'

    UNIQUE(id_coleta, concorrente, produto_id, categoria, variante_tipo, variante_nome)
);

CREATE INDEX IF NOT EXISTS idx_precos_produto ON precos(concorrente, produto_id, categoria);
CREATE INDEX IF NOT EXISTS idx_precos_coleta ON precos(id_coleta);
CREATE INDEX IF NOT EXISTS idx_coletas_mes ON coletas(mes_referencia);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Banco inicializado em: {DB_PATH}")


if __name__ == "__main__":
    init_db()
