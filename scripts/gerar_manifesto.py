"""Gera os manifestos que permitem conferir que foram usados os arquivos oficiais do TSE.

Uso:  python gerar_manifesto.py

Saida em resultados/:
  manifesto_logs.csv.gz  uma linha por secao da lista oficial: pasta (hash) no TSE,
                         nome e SHA-256 do log baixado, tamanho, ou o erro
  manifesto_bu.csv       os 28 arquivos de BU e o SHA-512 conferido (copia de dados/bu/manifesto.csv)
  manifesto_config.csv   SHA-256 das 28 listas oficiais de secoes (<uf>-p003221-cs.json)

Para conferir um log: baixe
  https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/dados/<uf>/<mun>/<zona>/<secao>/<hash_pasta>/<arquivo_log>
e compare o SHA-256 com o da linha correspondente.
"""
import csv, glob, gzip, hashlib, json, os, shutil

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CAMPOS = ["uf", "cd_mun", "zona", "secao", "hash_pasta", "arquivo_log", "sha256_log", "bytes_log", "erro"]


def main():
    os.makedirs(os.path.join(RAIZ, "resultados"), exist_ok=True)
    linhas = {}
    for caminho in sorted(glob.glob(os.path.join(RAIZ, "dados", "logs", "*.jsonl"))):
        if caminho.endswith("_teste.jsonl"):
            continue
        with open(caminho, encoding="utf-8") as f:
            for l in f:
                try:
                    r = json.loads(l)
                except json.JSONDecodeError:
                    continue
                k = (r["uf"], r["cd_mun"], r["zona"], r["secao"])
                if k in linhas and not linhas[k].get("erro"):
                    continue  # repetida por retomada da coleta: fica a versao com log
                linhas[k] = {c: r.get(c, "") for c in CAMPOS}

    saida = os.path.join(RAIZ, "resultados", "manifesto_logs.csv.gz")
    with gzip.open(saida, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(linhas[k] for k in sorted(linhas))
    com_log = sum(1 for r in linhas.values() if r["sha256_log"])
    print(f"manifesto_logs.csv.gz: {len(linhas)} secoes, {com_log} com SHA-256 do log, {os.path.getsize(saida) / 1e6:.1f} MB")

    shutil.copy2(os.path.join(RAIZ, "dados", "bu", "manifesto.csv"), os.path.join(RAIZ, "resultados", "manifesto_bu.csv"))
    print("manifesto_bu.csv: copiado")

    with open(os.path.join(RAIZ, "resultados", "manifesto_config.csv"), "w", encoding="utf-8") as f:
        f.write("arquivo,sha256\n")
        for caminho in sorted(glob.glob(os.path.join(RAIZ, "dados", "logs", "*-p003221-cs.json"))):
            with open(caminho, "rb") as g:
                f.write(f"{os.path.basename(caminho)},{hashlib.sha256(g.read()).hexdigest()}\n")
    print("manifesto_config.csv: gravado")


if __name__ == "__main__":
    main()
