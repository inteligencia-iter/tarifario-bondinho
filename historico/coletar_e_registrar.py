"""
Coleta o tarifario de todos os concorrentes e registra no banco historico,
em um unico passo. Este e o script pensado para rodar mensalmente
(manualmente ou via agendamento, ex: GitHub Actions).

Uso:
    python3 historico/coletar_e_registrar.py
    python3 historico/coletar_e_registrar.py --mes 2026-08     # forcar mes de referencia manualmente
    python3 historico/coletar_e_registrar.py --forcar          # permitir 2a coleta no mesmo mes

Codigos de saida (importante para CI/GitHub Actions):
    0 = sucesso (dados coletados e registrados) OU nada a fazer (coleta ja
        existia para o mes e --forcar nao foi passado -- isso NAO e um erro,
        e o comportamento esperado de um agendamento mensal que roda toda
        semana por seguranca, por exemplo)
    1 = erro real (falha ao coletar, banco inacessivel, etc.)

Se a variavel de ambiente GITHUB_OUTPUT existir (seta automaticamente pelo
GitHub Actions), o script escreve nela `coleta_realizada=true|false`, para
que o workflow decida se deve commitar o banco atualizado ou pular esse
passo.
"""
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from coletor_concorrentes import coletar_tudo
from inserir_snapshot import inserir_snapshot
from schema import init_db, get_connection

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots_brutos"


def coleta_ja_existe(mes_referencia: str) -> int | None:
    """Retorna o id_coleta mais recente ja registrado para este mes, ou None."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT id_coleta, data_coleta FROM coletas WHERE mes_referencia = ? ORDER BY id_coleta DESC LIMIT 1",
        (mes_referencia,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def emitir_output_github(coleta_realizada: bool):
    """Escreve no GITHUB_OUTPUT (se estivermos rodando dentro do GitHub Actions),
    para o workflow decidir se deve commitar o banco atualizado."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"coleta_realizada={'true' if coleta_realizada else 'false'}\n")


def main():
    mes_forcado = None
    if "--mes" in sys.argv:
        idx = sys.argv.index("--mes")
        mes_forcado = sys.argv[idx + 1]

    forcar = "--forcar" in sys.argv

    init_db()

    mes_referencia = mes_forcado or datetime.now(timezone.utc).strftime("%Y-%m")
    existente = coleta_ja_existe(mes_referencia)
    if existente and not forcar:
        id_antigo, data_antiga = existente
        print(
            f"[OK, nada a fazer] Ja existe uma coleta para o mes '{mes_referencia}' "
            f"(coleta #{id_antigo}, feita em {data_antiga}).\n"
            f"Isso nao e um erro -- e esperado se o agendamento rodar mais de "
            f"uma vez no mesmo mes. Se voce realmente quer registrar uma 2a "
            f"coleta neste mes (ex: para corrigir uma coleta com erro), rode "
            f"novamente com --forcar.\n"
            f"Nenhum dado foi coletado ou alterado.",
            file=sys.stderr,
        )
        emitir_output_github(coleta_realizada=False)
        sys.exit(0)  # nao e erro -- o workflow deve seguir sem commitar nada novo

    print("Coletando dados de todos os concorrentes...", file=sys.stderr)
    snapshot = coletar_tudo()

    # Guarda o snapshot bruto em disco tambem, como backup/auditoria --
    # o banco SQLite e a fonte de verdade para analise, mas ter o JSON
    # cru facilita re-processar ou depurar caso o schema mude no futuro.
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    snapshot_path = SNAPSHOTS_DIR / f"snapshot_{timestamp_str}.json"
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    print(f"Snapshot bruto salvo em: {snapshot_path}", file=sys.stderr)

    id_coleta, n_linhas = inserir_snapshot(snapshot, mes_referencia=mes_referencia)
    print(f"\nColeta #{id_coleta} registrada no historico: {n_linhas} linhas de preco.", file=sys.stderr)

    n_sites_ok = len(snapshot.get("sites", {}))
    n_sites_erro = len(snapshot.get("erros", {}))
    if snapshot.get("erros"):
        print(f"\n[ATENCAO] {n_sites_erro} site(s) falharam nesta coleta:", file=sys.stderr)
        for site, erro in snapshot["erros"].items():
            print(f"  - {site}: {erro}", file=sys.stderr)

    emitir_output_github(coleta_realizada=True)

    # Falha total (nenhum site coletado com sucesso) e um erro real -- so nesse
    # caso o job do CI deve ser marcado como falho. Falha parcial (alguns sites
    # falharam, outros nao) ainda registra o que deu certo e sai com sucesso,
    # mas o aviso acima fica visivel no log do Actions.
    if n_sites_ok == 0:
        print("\n[ERRO] Nenhum site foi coletado com sucesso.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
