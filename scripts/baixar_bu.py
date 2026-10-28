"""Baixa os Boletins de Urna (BU) do 2o turno de 2026 dos Dados Abertos do TSE
e confere o SHA-512 de cada arquivo contra o hash publicado pelo proprio TSE.

Uso:  python baixar_bu.py            # todas as UFs
      python baixar_bu.py AC RJ      # so algumas

Pode ser rodado de novo: arquivo ja baixado e com hash correto e pulado.
Grava dados/bu/manifesto.csv com uf, arquivo, tamanho, sha512 e data da checagem.
"""
import hashlib, json, os, sys, time, urllib.request

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dados", "bu")
CKAN = "https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026-boletim-de-urna"
UA = {"User-Agent": "Mozilla/5.0 (auditoria-2t pessoal)", "Cache-Control": "no-cache"}


def get(url, destino=None):
    for tentativa in range(5):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                if destino is None:
                    return r.read()
                with open(destino + ".parcial", "wb") as f:
                    while bloco := r.read(1 << 20):
                        f.write(bloco)
                os.replace(destino + ".parcial", destino)
                return None
        except Exception as e:
            print(f"   erro ({e}), tentando de novo em {2 ** tentativa}s")
            time.sleep(2 ** tentativa)
    raise RuntimeError(f"falhou: {url}")


def sha512(caminho):
    h = hashlib.sha512()
    with open(caminho, "rb") as f:
        while bloco := f.read(1 << 20):
            h.update(bloco)
    return h.hexdigest()


def main():
    os.makedirs(PASTA, exist_ok=True)
    so = {u.upper() for u in sys.argv[1:]}

    # lista de arquivos direto do catalogo do TSE (parametro anticache: a API ja devolveu versao velha)
    recursos = json.loads(get(f"{CKAN}&nocache={int(time.time())}"))["result"]["resources"]
    # o catalogo tem erro de cadastro (a entrada "Boletim" de RR aponta para o .sha512),
    # entao o endereco do zip e montado a partir de qualquer entrada do 2o turno
    zips = {r["url"].removesuffix(".sha512") for r in recursos if "Segundo turno" in r["name"]}
    print(f"{len(zips)} arquivos de BU do 2o turno no catalogo")

    manifesto = []
    for url in sorted(zips):
        nome = url.rsplit("/", 1)[1]
        uf = nome.split("_")[2]
        if so and uf not in so:
            continue
        caminho = os.path.join(PASTA, nome)
        esperado = get(url + ".sha512").decode().split()[0].lower()

        if os.path.exists(caminho) and sha512(caminho) == esperado:
            print(f"{uf}: ja baixado, hash ok")
        else:
            print(f"{uf}: baixando {nome} ...")
            get(url, caminho)
            obtido = sha512(caminho)
            if obtido != esperado:
                sys.exit(f"{uf}: HASH NAO CONFERE\n  esperado {esperado}\n  obtido   {obtido}\nParando.")
            print(f"{uf}: ok, {os.path.getsize(caminho) / 1e6:.1f} MB, hash confere")
        manifesto.append((uf, nome, os.path.getsize(caminho), esperado, time.strftime("%Y-%m-%d %H:%M:%S")))

    with open(os.path.join(PASTA, "manifesto.csv"), "w") as f:
        f.write("uf,arquivo,bytes,sha512,conferido_em\n")
        for linha in manifesto:
            f.write(",".join(map(str, linha)) + "\n")
    print(f"\n{len(manifesto)} arquivos conferidos. Manifesto em dados/bu/manifesto.csv")


if __name__ == "__main__":
    main()
