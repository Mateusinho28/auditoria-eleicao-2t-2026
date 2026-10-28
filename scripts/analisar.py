"""Junta BU (votos por candidato) e logs (horario de cada voto) e calcula, por urna,
UF e Brasil, quantos votos entraram de 8h a 17h e de 17h a 19h (horario de Brasilia)
e quanto disso, estimado, foi para cada candidato.

Uso:  python analisar.py

Entrada: dados/bu_presidente.csv.gz (extrair_bu.py) e dados/logs/<uf>.jsonl (coletar_logs.py)
Saida em resultados/:
  secoes.csv.gz     uma linha por urna, com as faixas de horario e a estimativa por candidato
  por_uf.csv        totais por UF
  por_municipio.csv totais por municipio
  por_minuto.csv    votos do Brasil inteiro por minuto (horario de Brasilia), para o grafico
  resumo.json       numeros principais, para o site

O log NAO diz em quem a pessoa votou (sigilo do voto). Por isso, por candidato:
  - estimativa: os votos de cada faixa seguem a proporcao da propria urna
    (urna com 60% Lula e 10 votos depois das 17h -> 6 Lula e 4 Flavio)
  - pior caso: todos os votos depois das 17h da urna para o mesmo candidato,
    limitado ao total que ele teve naquela urna
"""
import collections, csv, glob, gzip, json, os

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FAIXAS = ["antes_8h", "8h_17h", "17h_19h", "depois_19h", "sem_horario"]
TARDIOS = ["17h_19h", "depois_19h", "sem_horario"]  # o que conta como "depois das 17h"
CAND = ["lula", "flavio", "branco", "nulo"]


def seg(hhmm):
    h, m = hhmm.split(":")[:2]
    return int(h) * 3600 + int(m) * 60


def faixa(s):
    if s < 8 * 3600:
        return "antes_8h"
    if s < 17 * 3600:
        return "8h_17h"
    if s < 19 * 3600:
        return "17h_19h"
    return "depois_19h"


def hms(s):
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}"


def ler_logs():
    for caminho in sorted(glob.glob(os.path.join(RAIZ, "dados", "logs", "*.jsonl"))):
        if caminho.endswith("_teste.jsonl"):
            continue
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                try:
                    yield json.loads(linha)
                except json.JSONDecodeError:
                    pass


def main():
    bu = {}
    with gzip.open(os.path.join(RAIZ, "dados", "bu_presidente.csv.gz"), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = (r["uf"].lower(), r["cd_mun"], r["zona"], r["secao"])
            bu[k] = {"municipio": r["municipio"], "K": int(r["comparecimento"]), "aptos": int(r["aptos"]),
                     **{c: int(r[c]) for c in CAND}}

    # 1a passada: fuso de cada municipio. A urna abre as 8h de Brasilia, entao a hora
    # local da abertura revela o fuso (AC abre 6h local = 2h a menos que Brasilia).
    # Usa a hora mais comum entre as urnas do municipio (uma urna pode ter aberto atrasada).
    # (os logs sao lidos duas vezes do disco em vez de guardados: na memoria passariam de 10 GB)
    aberturas = collections.defaultdict(collections.Counter)
    com_log_bom = set()
    for r in ler_logs():
        if "erro" in r:
            continue
        com_log_bom.add((r["uf"], r["cd_mun"], r["zona"], r["secao"]))
        if r.get("pronta") and r["uf"] != "zz":
            aberturas[(r["uf"], r["cd_mun"])][round((seg(r["pronta"][0]) - 8 * 3600) / 3600)] += 1
    fuso = {m: c.most_common(1)[0][0] for m, c in aberturas.items()}

    # 2a passada: por urna, so o resumo (votos por faixa, encerramento, erro)
    logs, por_minuto = {}, collections.Counter()
    for r in ler_logs():
        k = (r["uf"], r["cd_mun"], r["zona"], r["secao"])
        if k in logs or ("erro" in r and k in com_log_bom):
            continue  # secao repetida por retomada da coleta: fica uma vez, a versao com log
        if "erro" in r:
            logs[k] = {"erro": r["erro"]}
            continue
        exterior = r["uf"] == "zz"
        # no exterior a votacao segue a hora local (8h-17h locais), sem prorrogacao
        desl = 0 if exterior else fuso.get((r["uf"], r["cd_mun"]), 0)
        n = dict.fromkeys(FAIXAS, 0)
        for minuto, q in r["votos_por_minuto"].items():
            s = seg(minuto) - desl * 3600
            n[faixa(s)] += q
            if not exterior and k[:2] in fuso:
                por_minuto[hms(s)] += q
        enc = hms(seg(r["encerramento"][-1]) - desl * 3600) if r.get("encerramento") else ""
        logs[k] = {"n": n, "enc": enc, "votos_dia": r["votos_dia"], "fuso_h": -desl}

    # cada urna do BU: grava a linha e ja soma nos totais (sem guardar as 500 mil linhas)
    os.makedirs(os.path.join(RAIZ, "resultados"), exist_ok=True)
    arq_secoes = gzip.open(os.path.join(RAIZ, "resultados", "secoes.csv.gz"), "wt", newline="", encoding="utf-8")
    w, numericas = None, None
    tot_uf = collections.defaultdict(collections.Counter)
    tot_mun = collections.defaultdict(collections.Counter)
    brasil, total = collections.Counter(), collections.Counter()
    conferencia = collections.Counter()
    for k in sorted(bu):
        b, r = bu[k], logs.get(k)
        uf, mun = k[0], k[1]
        exterior = uf == "zz"
        enc = ""
        if r is None or "erro" in r:
            conferencia["bu_sem_log"] += 1
            n = dict.fromkeys(FAIXAS, 0)
            n["sem_horario"] = b["K"]
            situacao = "sem log: " + (r["erro"] if r else "secao fora da lista do TSE")
        else:
            n, enc = r["n"], r["enc"]
            # votos que estao no BU mas nao aparecem no log com horario
            n["sem_horario"] = max(0, b["K"] - r["votos_dia"])
            if r["votos_dia"] == b["K"]:
                conferencia["log_igual_bu"] += 1
                situacao = "ok"
            else:
                conferencia["log_menor_bu" if r["votos_dia"] < b["K"] else "log_maior_bu"] += 1
                situacao = f"log {r['votos_dia']} x BU {b['K']}"

        tardios = sum(n[f] for f in TARDIOS)
        linha = {"uf": uf.upper(), "cd_mun": mun, "municipio": b["municipio"], "zona": k[2], "secao": k[3],
                 "fuso_h": 0 if r is None or "erro" in r else r["fuso_h"],
                 "encerramento_brasilia": enc, "estendida": enc >= "17:45",
                 "aptos": b["aptos"], "comparecimento": b["K"], **{c: b[c] for c in CAND},
                 **{f"votos_{f}": n[f] for f in FAIXAS}, "situacao": situacao}
        for f in FAIXAS + ["tardios"]:
            q = tardios if f == "tardios" else n[f]
            for c in CAND:
                linha[f"est_{c}_{f}"] = q * b[c] / b["K"] if b["K"] else 0.0
        # pior caso: todos os tardios para um candidato so, ate o que ele teve na urna
        linha["max_lula_tardios"] = min(b["lula"], tardios)
        linha["max_flavio_tardios"] = min(b["flavio"], tardios)

        if w is None:
            w = csv.DictWriter(arq_secoes, fieldnames=list(linha))
            w.writeheader()
            # agregacoes: soma de todas as colunas numericas
            numericas = [c for c, v in linha.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and c != "fuso_h"]
        w.writerow({c: round(v, 4) if isinstance(v, float) else v for c, v in linha.items()})
        grupos = [tot_uf[linha["uf"]], tot_mun[(linha["uf"], mun, linha["municipio"])], total]
        if not exterior:
            grupos.append(brasil)
        for t in grupos:
            t["urnas"] += 1
            t["urnas_estendidas"] += linha["estendida"]
            for c in numericas:
                t[c] += linha[c]
    arq_secoes.close()
    tot_uf = dict(sorted(tot_uf.items()))

    # secoes da lista do TSE que nao estao no BU (agregadas, nao instaladas...)
    for k, r in logs.items():
        if k not in bu:
            conferencia["log_sem_bu: " + r.get("erro", "com log")] += 1

    def gravar(nome, chaves, itens):
        with open(os.path.join(RAIZ, "resultados", nome), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(chaves + ["urnas", "urnas_estendidas"] + numericas)
            for k, t in itens:
                w.writerow(list(k) + [t["urnas"], t["urnas_estendidas"]] + [round(t[c], 1) for c in numericas])

    gravar("por_uf.csv", ["uf"], [((uf,), t) for uf, t in tot_uf.items()] + [(("BRASIL sem exterior",), brasil), (("TOTAL",), total)])
    gravar("por_municipio.csv", ["uf", "cd_mun", "municipio"],
           sorted(tot_mun.items(), key=lambda kt: -kt[1]["votos_17h_19h"]))
    with open(os.path.join(RAIZ, "resultados", "por_minuto.csv"), "w", encoding="utf-8") as f:
        f.write("hora_brasilia,votos\n")
        for m in sorted(por_minuto):
            f.write(f"{m},{por_minuto[m]}\n")

    dif = total["lula"] - total["flavio"]
    resumo = {
        "conferencia": dict(conferencia),
        "diferenca_oficial": dif,
        "brasil_sem_exterior": {c: round(brasil[c], 1) for c in ["urnas", "urnas_estendidas"] + numericas},
        "total_com_exterior": {c: round(total[c], 1) for c in ["urnas", "urnas_estendidas"] + numericas},
        "por_uf": {uf: {c: round(t[c], 1) for c in ["urnas", "urnas_estendidas"] + numericas} for uf, t in tot_uf.items()},
    }
    with open(os.path.join(RAIZ, "resultados", "resumo.json"), "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=1)

    # relatorio no terminal
    p = lambda x: f"{round(x):,}".replace(",", ".")
    print("CONFERENCIA BU x LOG")
    for c, q in sorted(conferencia.items()):
        print(f"  {c:55}{p(q):>10}")
    for titulo, t in [("BRASIL (sem exterior), horario de Brasilia", brasil), ("TOTAL com exterior (exterior em hora local)", total)]:
        print(f"\n{titulo}: {p(t['urnas'])} urnas, {p(t['urnas_estendidas'])} encerradas depois das 17h45")
        print(f"  {'faixa':14}{'votos':>14}{'Lula (est.)':>14}{'Flavio (est.)':>15}{'branco':>10}{'nulo':>10}")
        for fx in FAIXAS:
            print(f"  {fx:14}{p(t['votos_' + fx]):>14}{p(t['est_lula_' + fx]):>14}{p(t['est_flavio_' + fx]):>15}"
                  f"{p(t['est_branco_' + fx]):>10}{p(t['est_nulo_' + fx]):>10}")
        print(f"  {'total':14}{p(t['comparecimento']):>14}{p(t['lula']):>14}{p(t['flavio']):>15}{p(t['branco']):>10}{p(t['nulo']):>10}")
    t = total
    print(f"\nDiferenca oficial Lula - Flavio: {p(dif)}")
    print(f"Depois das 17h (17h-19h + depois das 19h + sem horario): {p(t['votos_tardios'] if 'votos_tardios' in t else sum(t['votos_' + f] for f in TARDIOS))} votos")
    print(f"  estimativa: Lula {p(t['est_lula_tardios'])}, Flavio {p(t['est_flavio_tardios'])}")
    print(f"  pior caso: se todos fossem do Lula (no maximo {p(t['max_lula_tardios'])}), a diferenca sem eles seria {p(dif - t['max_lula_tardios'])}")
    print(f"             se todos fossem do Flavio (no maximo {p(t['max_flavio_tardios'])}), a diferenca sem eles seria {p(dif + t['max_flavio_tardios'])}")
    print("\nArquivos em resultados/")


if __name__ == "__main__":
    main()
