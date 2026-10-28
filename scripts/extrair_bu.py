"""Extrai dos BUs baixados os votos de Presidente por secao e confere a soma
com o resultado oficial publicado pelo TSE.

Uso:  python extrair_bu.py

Entrada: dados/bu/bweb_2t_*.zip (baixados e conferidos por baixar_bu.py)
Saida:   dados/bu_presidente.csv.gz, uma linha por secao (urna) com eleitorado,
         comparecimento, votos de cada candidato, branco, nulo e horarios do BU
         dados/oficial_br.json, copia do resultado oficial usado na conferencia
"""
import csv, glob, gzip, io, json, os, sys, time, urllib.request, zipfile

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OFICIAL = "https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json"
CANDIDATOS = {"13": "lula", "22": "flavio"}
CAMPOS = ["uf", "cd_mun", "municipio", "zona", "secao", "aptos", "comparecimento",
          "lula", "flavio", "branco", "nulo", "abertura", "encerramento", "tipo_urna",
          "nr_urna", "secoes_agregadas"]


def ler_zip(caminho):
    with zipfile.ZipFile(caminho) as z:
        nome = next(n for n in z.namelist() if n.endswith(".csv"))
        with z.open(nome) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";")


def main():
    secoes = {}
    for caminho in sorted(glob.glob(os.path.join(RAIZ, "dados", "bu", "bweb_2t_*.zip"))):
        n = 0
        for r in ler_zip(caminho):
            if r["DS_CARGO_PERGUNTA"] != "Presidente":
                continue
            n += 1
            # codigos com zero a esquerda, no mesmo formato dos enderecos dos logs
            k = (r["SG_UF"], r["CD_MUNICIPIO"].zfill(5), r["NR_ZONA"].zfill(4), r["NR_SECAO"].zfill(4))
            s = secoes.get(k)
            if s is None:
                s = secoes[k] = {
                    "uf": k[0], "cd_mun": k[1], "municipio": r["NM_MUNICIPIO"], "zona": k[2], "secao": k[3],
                    "aptos": int(r["QT_APTOS"]), "comparecimento": int(r["QT_COMPARECIMENTO"]),
                    "lula": 0, "flavio": 0, "branco": 0, "nulo": 0,
                    "abertura": r["DT_ABERTURA"], "encerramento": r["DT_ENCERRAMENTO"],
                    "tipo_urna": r["DS_TIPO_URNA"], "nr_urna": r["NR_URNA_EFETIVADA"],
                    "secoes_agregadas": "" if r["DS_SECOES_AGREGADAS"] == "#NULO#" else r["DS_SECOES_AGREGADAS"]}
            votos = int(r["QT_VOTOS"])
            tipo = r["CD_TIPO_VOTAVEL"]  # 1 nominal, 2 branco, 3 nulo
            if tipo == "1":
                s[CANDIDATOS[r["NR_VOTAVEL"]]] += votos
            elif tipo == "2":
                s["branco"] += votos
            elif tipo == "3":
                s["nulo"] += votos
            else:
                sys.exit(f"tipo de votavel inesperado: {tipo} em {k}")
        print(f"{os.path.basename(caminho)}: {n} linhas de Presidente")

    # consistencia interna de cada secao: votos somam o comparecimento
    ruins = [k for k, s in secoes.items() if s["lula"] + s["flavio"] + s["branco"] + s["nulo"] != s["comparecimento"]]
    print(f"\n{len(secoes)} secoes; {len(ruins)} com soma de votos diferente do comparecimento")

    saida = os.path.join(RAIZ, "dados", "bu_presidente.csv.gz")
    with gzip.open(saida, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(secoes[k] for k in sorted(secoes))
    print(f"gravado {saida}")

    # conferencia com o resultado oficial
    req = urllib.request.Request(f"{OFICIAL}?nocache={int(time.time())}", headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=60).read()
    with open(os.path.join(RAIZ, "dados", "oficial_br.json"), "wb") as f:
        f.write(raw)
    of = json.loads(raw)
    cand = {c["n"]: int(c["vap"]) for a in of["carg"][0]["agr"] for p in a["par"] for c in p["cand"]}
    # si/esi = secoes instaladas e seu eleitorado (o total "te" inclui 41 secoes do exterior nao instaladas)
    oficial = {"secoes": int(of["s"]["si"]), "aptos": int(of["e"]["esi"]), "comparecimento": int(of["e"]["c"]),
               "lula": cand["13"], "flavio": cand["22"], "branco": int(of["v"]["vb"]), "nulo": int(of["v"]["tvn"])}
    soma = {c: sum(s[c] for s in secoes.values()) for c in oficial if c != "secoes"}
    soma["secoes"] = len(secoes)

    print(f"\nconferencia com o oficial do TSE (gerado {of['dg']} {of['hg']}):")
    print(f"{'':16}{'soma dos BUs':>15}{'oficial':>15}{'diferenca':>12}")
    for c in oficial:
        print(f"{c:16}{soma[c]:>15,}{oficial[c]:>15,}{soma[c] - oficial[c]:>12,}".replace(",", "."))


if __name__ == "__main__":
    main()
