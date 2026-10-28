"""Gera site/dados.json a partir dos arquivos de resultados/ (saida de analisar.py)
e copia os CSVs para site/dados/, de onde o site oferece o download.

Uso:  python gerar_dados_site.py
"""
import csv, json, os, shutil

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RES = os.path.join(RAIZ, "resultados")


def num(v):
    f = float(v)
    return int(f) if f == int(f) else round(f, 1)


def ler(nome):
    with open(os.path.join(RES, nome), encoding="utf-8") as f:
        return [{k: (v if k in ("uf", "cd_mun", "municipio") else num(v)) for k, v in r.items()} for r in csv.DictReader(f)]


def resumo_linha(r):
    """So as colunas que o site mostra."""
    return {"urnas": r["urnas"], "estendidas": r["urnas_estendidas"], "comparecimento": r["comparecimento"],
            "lula": r["lula"], "flavio": r["flavio"], "branco": r["branco"], "nulo": r["nulo"],
            "v8_17": r["votos_8h_17h"], "v17_19": r["votos_17h_19h"], "v19": r["votos_depois_19h"],
            "sem_h": r["votos_sem_horario"],
            "lula_17_19": round(r["est_lula_17h_19h"]), "flavio_17_19": round(r["est_flavio_17h_19h"]),
            "lula_tard": round(r["est_lula_tardios"]), "flavio_tard": round(r["est_flavio_tardios"]),
            "max_lula": r["max_lula_tardios"], "max_flavio": r["max_flavio_tardios"]}


def main():
    with open(os.path.join(RES, "resumo.json"), encoding="utf-8") as f:
        resumo = json.load(f)
    def faixas(t):
        return {fx: {"votos": t[f"votos_{fx}"], **{c: round(t[f"est_{c}_{fx}"]) for c in ("lula", "flavio", "branco", "nulo")}}
                for fx in ("antes_8h", "8h_17h", "17h_19h", "depois_19h", "sem_horario")}

    uf = ler("por_uf.csv")
    mun = ler("por_municipio.csv")
    with open(os.path.join(RES, "por_minuto.csv"), encoding="utf-8") as f:
        minuto = [[r["hora_brasilia"], int(r["votos"])] for r in csv.DictReader(f)]

    dados = {
        "diferenca": resumo["diferenca_oficial"],
        "conferencia": resumo["conferencia"],
        "brasil": {**resumo_linha({**resumo["brasil_sem_exterior"]}), "faixas": faixas(resumo["brasil_sem_exterior"])},
        "total": {**resumo_linha({**resumo["total_com_exterior"]}), "faixas": faixas(resumo["total_com_exterior"])},
        "uf": [{"uf": r["uf"], **resumo_linha(r)} for r in uf if len(r["uf"]) == 2],
        "municipios": [[r["uf"], r["municipio"], r["urnas"], r["urnas_estendidas"], r["comparecimento"],
                        r["votos_8h_17h"], r["votos_17h_19h"] + r["votos_depois_19h"], r["votos_sem_horario"],
                        round(r["est_lula_tardios"]), round(r["est_flavio_tardios"])] for r in mun],
        "por_minuto": minuto,
    }
    os.makedirs(os.path.join(RAIZ, "site"), exist_ok=True)
    with open(os.path.join(RAIZ, "site", "dados.json"), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    print(f"site/dados.json: {len(dados['uf'])} UFs, {len(dados['municipios'])} municipios, {len(minuto)} minutos")

    # arquivos para download
    destino = os.path.join(RAIZ, "site", "dados")
    os.makedirs(destino, exist_ok=True)
    for nome in ("por_uf.csv", "por_municipio.csv", "por_minuto.csv", "secoes.csv.gz", "resumo.json"):
        shutil.copy2(os.path.join(RES, nome), os.path.join(destino, nome))
        print(f"site/dados/{nome}: {os.path.getsize(os.path.join(destino, nome)) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
