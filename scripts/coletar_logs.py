"""Coleta o log (logd.dat) de cada urna do 2o turno de 2026 direto do site de
resultados do TSE e guarda, por urna, os horarios de votacao.

Uso:  python coletar_logs.py                 # todas as UFs
      python coletar_logs.py rj ac           # so algumas
      python coletar_logs.py --teste 20 rj   # so as 20 primeiras secoes (para testar)
Variaveis: RPS (requisicoes por segundo, padrao 20), WORKERS (padrao 24)

Caminho no TSE, para cada secao:
  config/<uf>/<uf>-p003221-cs.json                     lista de secoes da UF
  dados/<uf>/<mun>/<zona>/<secao>/...-aux.json        pasta (hash) e arquivos da urna
  dados/<uf>/<mun>/<zona>/<secao>/<hash>/...-log.jez  log da urna (zip com logd.dat)

Grava dados/logs/<uf>.jsonl, uma linha por secao, com o SHA-256 do log baixado,
os votos de 25/10/2026 agregados por minuto (relogio local da urna) e os eventos
de abertura e encerramento. O log em si nao e guardado (sao dezenas de GB).
Pode ser interrompido e rodado de novo: continua de onde parou.
"""
import concurrent.futures as cf, hashlib, io, json, os, random, subprocess, sys, tempfile
import threading, time, urllib.error, urllib.request, zipfile

BASE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221"
PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dados", "logs")
UFS = "ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz".split()
DIA = "25/10/2026"
RPS = float(os.environ.get("RPS", "20"))
WORKERS = int(os.environ.get("WORKERS", "24"))

trava_print = threading.Lock()


def log(msg):
    with trava_print:
        print(time.strftime("%H:%M:%S"), msg, flush=True)


class Limitador:
    """Segura o ritmo de requisicoes; se o TSE reclamar (403/429), reduz e espera."""

    def __init__(self, rps):
        self.rps, self.trava, self.proximo = rps, threading.Lock(), time.monotonic()

    def esperar(self):
        with self.trava:
            agora = time.monotonic()
            self.proximo = max(self.proximo, agora) + 1 / self.rps
            espera = self.proximo - agora - 1 / self.rps
        if espera > 0:
            time.sleep(espera)

    def reduzir(self):
        with self.trava:
            self.rps = max(2, self.rps * 0.7)
            self.proximo = time.monotonic() + 30
        log(f"servidor reclamou: reduzindo para {self.rps:.1f} req/s")


lim = Limitador(RPS)


def get(url):
    for tentativa in range(8):
        lim.esperar()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (auditoria-2t pessoal)"})
            return urllib.request.urlopen(req, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if e.code in (403, 429):
                lim.reduzir()
        except Exception:
            if tentativa >= 2:
                lim.reduzir()
        time.sleep(min(60, 2 ** tentativa) + random.random())
    raise RuntimeError(f"falhou 8 vezes: {url}")


def textos_do_jez(raw):
    """O .jez e um zip com o logd.dat. Em urna de contingencia (substituida no dia)
    vem outro .jez dentro, com o log da urna original: abre tudo recursivamente."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        conteudo = [(n, z.read(n)) for n in z.namelist()]
    except (zipfile.BadZipFile, NotImplementedError):
        conteudo = abrir_com_7z(raw)
    for nome, dados in conteudo:
        if nome.lower().endswith(".jez"):
            yield from textos_do_jez(dados)
        elif nome.lower().endswith(".dat"):
            yield nome, dados.decode("latin-1")


def abrir_com_7z(raw):
    with tempfile.TemporaryDirectory() as d:
        arq, saida = os.path.join(d, "x.jez"), os.path.join(d, "out")
        with open(arq, "wb") as f:
            f.write(raw)
        subprocess.run(["7z", "x", "-y", f"-o{saida}", arq], capture_output=True, check=True)
        res = []
        for raiz, _, nomes in os.walk(saida):
            for n in nomes:
                with open(os.path.join(raiz, n), "rb") as f:
                    res.append((n, f.read()))
        return res


def ler_log(raw):
    vistos, por_minuto = set(), {}
    r = {"arquivos_log": [], "votos_dia": 0, "votos_duplicados": 0, "votos_outro_dia": 0,
         "pronta": [], "encerramento": [], "modelo": None, "id_urna": []}
    for nome, txt in textos_do_jez(raw):
        r["arquivos_log"].append(nome)
        for linha in txt.splitlines():
            c = linha.split("\t")
            if len(c) < 5:
                continue
            dt, id_urna, msg = c[0], c[2], c[4]
            if msg == "O voto do eleitor foi computado":
                # a mesma linha pode aparecer duas vezes quando o log da urna original
                # vem junto com o da urna de contingencia
                chave = (dt, id_urna, c[5] if len(c) > 5 else "")
                if chave in vistos:
                    r["votos_duplicados"] += 1
                    continue
                vistos.add(chave)
                if not dt.startswith(DIA):
                    r["votos_outro_dia"] += 1
                    continue
                m = dt[11:16]
                por_minuto[m] = por_minuto.get(m, 0) + 1
                r["votos_dia"] += 1
            elif dt.startswith(DIA):
                if msg == "Urna pronta para receber votos":
                    r["pronta"].append(dt[11:])
                elif msg == "Procedimento de encerramento confirmado":
                    r["encerramento"].append(dt[11:])
                elif msg.startswith("Identificação do Modelo de Urna"):
                    r["modelo"] = msg.split(":")[-1].strip()
                if id_urna not in r["id_urna"]:
                    r["id_urna"].append(id_urna)
    r["votos_por_minuto"] = dict(sorted(por_minuto.items()))
    return r


def secao(uf, mun, nome_mun, zona, sec):
    pasta = f"{BASE}/dados/{uf}/{mun}/{zona}/{sec}"
    out = {"uf": uf, "cd_mun": mun, "municipio": nome_mun, "zona": zona, "secao": sec}
    try:
        aux = json.loads(get(f"{pasta}/p003221-{uf}-m{mun}-z{zona}-s{sec}-aux.json"))
    except urllib.error.HTTPError as e:
        return {**out, "erro": f"aux {e.code}"}
    hashes = aux.get("hashes", [])
    out["st"] = aux.get("st")
    if not hashes:
        return {**out, "erro": "sem pasta de arquivos"}
    # se houver mais de uma pasta, usa a que foi totalizada (ou a ultima)
    h = next((x for x in reversed(hashes) if x.get("st") == "Totalizado"), hashes[-1])
    out.update(hash_pasta=h["hash"], st_pasta=h.get("st"), recebido=f'{h.get("dr")} {h.get("hr")}',
               n_pastas=len(hashes), tipos=[a.get("tp") for a in h.get("arq", [])])
    logs = [a["nm"] for a in h.get("arq", []) if a.get("tp") == "log"]
    if not logs:
        if aux.get("st") == "Nao instalada":
            return {**out, "erro": "secao nao instalada"}
        if "logsa" in out["tipos"]:  # votou em papel/sistema de apuracao, sem log de urna
            return {**out, "erro": "sem log de urna (sistema de apuracao)"}
        return {**out, "erro": "sem log"}
    try:
        raw = get(f"{pasta}/{h['hash']}/{logs[0]}")
    except urllib.error.HTTPError as e:
        return {**out, "erro": f"log {e.code}"}
    out["arquivo_log"], out["sha256_log"], out["bytes_log"] = logs[0], hashlib.sha256(raw).hexdigest(), len(raw)
    try:
        return {**out, **ler_log(raw)}
    except Exception as e:
        return {**out, "erro": f"log ilegivel: {e}"}


def main():
    args = sys.argv[1:]
    teste = None
    if args[:1] == ["--teste"]:
        teste, args = int(args[1]), args[2:]
    ufs = [u.lower() for u in args] or UFS
    os.makedirs(PASTA, exist_ok=True)

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for uf in ufs:
            caminho = os.path.join(PASTA, f"{uf}{'_teste' if teste else ''}.jsonl")
            feitas = set()
            if os.path.exists(caminho):
                for l in open(caminho, encoding="utf-8"):
                    try:
                        r = json.loads(l)
                    except json.JSONDecodeError:
                        continue  # linha cortada por interrupcao
                    if not str(r.get("erro", "")).startswith("excecao"):
                        feitas.add((r["cd_mun"], r["zona"], r["secao"]))

            cs_raw = get(f"{BASE}/config/{uf}/{uf}-p003221-cs.json")
            with open(os.path.join(PASTA, f"{uf}-p003221-cs.json"), "wb") as f:
                f.write(cs_raw)  # guarda a lista oficial de secoes usada
            cs = json.loads(cs_raw)
            todas = [(m["cd"], m["nm"], z["cd"], s["ns"]) for m in cs["abr"][0]["mu"] for z in m["zon"] for s in z["sec"]]
            if teste:
                todas = todas[:teste]
            falta = [t for t in todas if (t[0], t[2], t[3]) not in feitas]
            log(f"{uf}: {len(todas)} secoes, {len(falta)} a baixar")

            t0 = time.time()
            with open(caminho, "a", encoding="utf-8") as f:
                futuros = {ex.submit(secao, uf, *t): t for t in falta}
                for i, fu in enumerate(cf.as_completed(futuros), 1):
                    try:
                        r = fu.result()
                    except Exception as e:
                        mun, nm, zona, sec = futuros[fu]
                        r = {"uf": uf, "cd_mun": mun, "municipio": nm, "zona": zona, "secao": sec, "erro": f"excecao {e}"}
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    if i % 1000 == 0:
                        f.flush()
                        ritmo = i / (time.time() - t0)
                        log(f"{uf}: {i}/{len(falta)} ({ritmo:.1f} secoes/s, faltam ~{(len(falta) - i) / ritmo / 60:.0f} min)")
            log(f"{uf}: concluido")


if __name__ == "__main__":
    main()
