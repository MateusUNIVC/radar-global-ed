"""
Classificação temática de editais.

Recebe um título (e a URL) e devolve:
  - temas encontrados (internacional, mobilidade, cotutela, pesquisa, ...)
  - status do documento (aberto / resultado / retificação / encerrado)
  - se é ruído (menu, rodapé, paginação) e deve ser descartado
  - uma pontuação de relevância usada para ordenar o painel

Detalhe de implementação importante: palavras-chave com mais de um termo
casam mesmo com palavras no meio. "joint supervision" encontra
"joint PhD supervision"; "dupla titulacao" encontra "dupla titulação
internacional". Sem isso, muitos editais reais escapavam.
"""

import json
import re
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TEMAS_FILE = BASE_DIR / "temas.json"

# Peso por prioridade declarada em temas.json (1 = mais relevante)
PESO_PRIORIDADE = {1: 10, 2: 4, 3: 2}

# Quantas palavras podem aparecer entre os termos de uma palavra-chave composta
GAP_MAXIMO = 2

# Sinais geográficos: um edital que menciona país estrangeiro, mesmo sem dizer
# "internacional", quase sempre é de cooperação externa.
PAISES_E_GENTILICOS = [
    "alemanha", "alemao", "alema", "germany", "german",
    "franca", "frances", "francesa", "france", "french",
    "portugal", "portugues", "portuguesa",
    "espanha", "espanhol", "espanhola", "spain", "spanish",
    "italia", "italiano", "italiana", "italy", "italian",
    "reino unido", "inglaterra", "united kingdom", "britanic", "british",
    "estados unidos", "united states", "americano",
    "canada", "canadense", "canadian",
    "japao", "japones", "japonesa", "japan", "japanese",
    "china", "chines", "chinesa", "chinese",
    "coreia", "korea", "korean",
    "argentina", "argentino", "chile", "chileno", "uruguai", "paraguai",
    "colombia", "peru", "mexico", "mexicano", "bolivia", "equador",
    "holanda", "paises baixos", "netherlands", "dutch",
    "belgica", "belgian", "suica", "switzerland", "swiss",
    "suecia", "sweden", "noruega", "norway", "dinamarca", "denmark",
    "finlandia", "finland", "austria", "irlanda", "ireland",
    "australia", "nova zelandia", "new zealand",
    "mocambique", "angola", "cabo verde", "africa do sul", "south africa",
    "india", "israel", "turquia", "polonia", "poland",
    "republica tcheca", "hungria", "romenia", "grecia", "greece",
    "uniao europeia", "european union", "mercosul", "brics",
    "ibero americ", "iberoameric", "latin america", "america latina",
    "europa", "europe", "europeu", "europeia",
]

# Termos típicos de chamada estrangeira
SINAIS_IDIOMA_ESTRANGEIRO = [
    "call for", "applications are", "apply now",
    "appel a candidatures", "appel a projets", "convocatoria",
    "how to apply", "eligibility",
]


def normalizar(texto):
    """Minúsculas, sem acento, espaços colapsados — para casar palavra-chave."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def compilar_padrao(palavra_norm):
    """
    Constrói a regex de uma palavra-chave.

    - Um termo só: casa como prefixo ('retificad' pega 'retificada',
      'retificados'), ancorado no início da palavra.
    - Vários termos: casa em ordem, tolerando até GAP_MAXIMO palavras no meio.
    """
    termos = [t for t in palavra_norm.split() if t]
    if not termos:
        return None

    partes = [r"\b" + re.escape(termos[0])]
    for termo in termos[1:]:
        partes.append(r"(?:\s+\w+){0,%d}\s+" % GAP_MAXIMO + re.escape(termo))
    return re.compile("".join(partes))


def titulo_do_slug(url):
    """Deriva um título legível do final da URL, para links sem texto."""
    if not url:
        return ""
    slug = url.rstrip("/").split("/")[-1]
    slug = re.sub(r"\.(pdf|html?|aspx?|php)$", "", slug, flags=re.I)
    slug = re.sub(r"[-_+]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    return slug


class Classificador:
    def __init__(self, caminho_temas=None):
        caminho = Path(caminho_temas) if caminho_temas else TEMAS_FILE
        with open(caminho, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        self.temas = {
            chave: valor
            for chave, valor in cfg["temas_interesse"].items()
            if not chave.startswith("_")
        }
        self.status_defs = {
            chave: valor
            for chave, valor in cfg["status_edital"].items()
            if not chave.startswith("_")
        }
        self.ruido = [normalizar(p) for p in cfg["ruido"]["palavras"]]

        # Reforça o tema 'internacional' com países e sinais de idioma.
        if "internacional" in self.temas:
            self.temas["internacional"]["palavras"] = (
                self.temas["internacional"]["palavras"]
                + PAISES_E_GENTILICOS
                + SINAIS_IDIOMA_ESTRANGEIRO
            )

        # Pré-compila todos os padrões uma única vez.
        for tema in self.temas.values():
            tema["_padroes"] = [
                p for p in (compilar_padrao(normalizar(w)) for w in tema["palavras"]) if p
            ]
        for st in self.status_defs.values():
            st["_padroes"] = [
                p for p in (compilar_padrao(normalizar(w)) for w in st["palavras"]) if p
            ]

    # ------------------------------------------------------------------ #

    def eh_ruido(self, titulo):
        """True se o link é claramente navegação/rodapé e não um edital."""
        t = normalizar(titulo)
        if len(t) < 12:
            return True
        if re.fullmatch(r"[\d\s]+", t):  # paginação / data solta
            return True
        for palavra in self.ruido:
            if not palavra:
                continue
            if t == palavra:
                return True
            if palavra in t and len(palavra) / len(t) > 0.6:
                return True
        return False

    def detectar_temas(self, texto_norm):
        encontrados = []
        for chave, tema in self.temas.items():
            for padrao in tema["_padroes"]:
                if padrao.search(texto_norm):
                    encontrados.append(chave)
                    break
        return encontrados

    def detectar_status(self, texto_norm):
        # ordem importa: 'encerrado' > 'resultado' > 'retificacao'
        for chave in ("encerrado", "resultado", "retificacao"):
            st = self.status_defs.get(chave)
            if not st:
                continue
            for padrao in st["_padroes"]:
                if padrao.search(texto_norm):
                    return chave
        return "aberto"

    def pontuar(self, temas, status, forcado_internacional):
        pontos = 0
        for chave in temas:
            prioridade = self.temas[chave].get("prioridade", 3)
            pontos += PESO_PRIORIDADE.get(prioridade, 2)

        eh_intl = "internacional" in temas or forcado_internacional

        # combinações que interessam especialmente ao DRI
        if eh_intl:
            pontos += 8
        if "cotutela" in temas:
            pontos += 6
        if "mobilidade" in temas:
            pontos += 4
        if eh_intl and ("mobilidade" in temas or "cotutela" in temas):
            pontos += 6

        # documentos que não são a abertura em si valem menos
        if status == "resultado":
            pontos = max(1, int(pontos * 0.45))
        elif status == "retificacao":
            pontos = max(1, int(pontos * 0.7))
        elif status == "encerrado":
            pontos = max(1, int(pontos * 0.25))

        return pontos

    def classificar(self, titulo, url="", sempre_internacional=False, texto_extra="", permitir_sem_tema=False):
        """Classifica titulo/URL e, quando disponivel, o texto da pagina de detalhe."""
        titulo = (titulo or "").strip()
        if not titulo:
            titulo = titulo_do_slug(url)

        if self.eh_ruido(titulo):
            return None

        # A URL ajuda: o slug muitas vezes diz mais que o texto do link.
        texto_norm = " ".join([
            normalizar(titulo),
            normalizar(titulo_do_slug(url)),
            normalizar(url.replace("-", " ").replace("/", " ")),
            normalizar(texto_extra),
        ])

        temas = self.detectar_temas(texto_norm)

        if sempre_internacional and "internacional" not in temas:
            temas.append("internacional")

        # Relevância mínima: precisa casar com pelo menos um tema.
        if not temas and not permitir_sem_tema:
            return None

        status = self.detectar_status(texto_norm)
        pontos = self.pontuar(temas, status, sempre_internacional)

        return {
            "titulo_limpo": titulo,
            "temas": sorted(temas, key=lambda c: self.temas[c].get("prioridade", 3)),
            "status": status,
            "pontos": pontos,
        }

    def rotulos(self):
        """Metadados dos temas para o painel montar filtros e cores."""
        return {
            chave: {"rotulo": t["rotulo"], "cor": t["cor"]}
            for chave, t in self.temas.items()
        }
