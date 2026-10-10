"""O que o programa aprendeu sobre cada forma de capturar, guardado em disco.

As preferencias simples continuam no `QSettings`
([0017](../docs/adr/0017-preferencias-em-qsettings.md)); aqui mora o que e
estruturado e por dispositivo: o modo escolhido, o perfil e a qualidade, e o
resultado de «Testar equipamento», modo a modo.

A promessa deste modulo e nunca atrapalhar. Toda funcao engole as suas
excecoes: um banco corrompido, um disco cheio ou uma pasta somente-leitura
custam a memoria das escolhas, nunca a captura — que e o que o usuario veio
fazer. Ver [0025](../docs/adr/0025-memoria-de-escolhas-por-dispositivo.md).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .dispositivos import ModoVideo, pasta_dados

# Medicao envelhece: ela mede esta maquina, e a maquina muda — driver novo,
# outra carga, a placa noutra porta USB. Meio ano e tempo de sobra para quem
# usa sempre o mesmo equipamento, e curto o bastante para nao ressuscitar um
# veredito de outro mundo.
VALIDADE_MEDICAO_S = 180 * 24 * 3600

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS escolha (
    chave      TEXT PRIMARY KEY,
    codec      TEXT,
    largura    INTEGER,
    altura     INTEGER,
    fps        REAL,
    perfil     TEXT,
    qualidade  INTEGER,
    visto_em   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS medicao (
    chave              TEXT NOT NULL,
    codec              TEXT NOT NULL,
    largura            INTEGER NOT NULL,
    altura             INTEGER NOT NULL,
    fps                REAL NOT NULL,
    quadros_reais      INTEGER NOT NULL,
    quadros_vazios     INTEGER NOT NULL,
    duracao            REAL NOT NULL,
    octetos            INTEGER NOT NULL,
    erro               TEXT NOT NULL,
    ms_por_quadro      REAL NOT NULL,
    quadros_processados INTEGER NOT NULL,
    medido_em          REAL NOT NULL,
    PRIMARY KEY (chave, codec, largura, altura, fps)
);
"""


def caminho_banco() -> Path:
    return pasta_dados() / "memoria.sqlite3"


def _conectar() -> sqlite3.Connection | None:
    try:
        conexao = sqlite3.connect(caminho_banco(), timeout=2.0)
        # Duas janelas do programa abertas ao mesmo tempo nao sao o caso de uso,
        # mas tambem nao podem corromper nada: o WAL resolve os dois lados.
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.executescript(_ESQUEMA)
        return conexao
    except (sqlite3.Error, OSError):
        return None


# --------------------------------------------------------------------------
# Escolha do usuario
# --------------------------------------------------------------------------

def lembrar_escolha(chave: str, modo: ModoVideo | None,
                    perfil: str = "", qualidade: int | None = None) -> None:
    """Grava o que este dispositivo estava usando. Chave vazia nao guarda nada."""
    if not chave:
        return
    conexao = _conectar()
    if conexao is None:
        return
    try:
        with conexao:
            conexao.execute(
                "INSERT INTO escolha"
                " (chave, codec, largura, altura, fps, perfil, qualidade, visto_em)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(chave) DO UPDATE SET"
                "   codec=excluded.codec, largura=excluded.largura,"
                "   altura=excluded.altura, fps=excluded.fps,"
                "   perfil=excluded.perfil, qualidade=excluded.qualidade,"
                "   visto_em=excluded.visto_em",
                (chave,
                 modo.codec if modo else None,
                 modo.largura if modo else None,
                 modo.altura if modo else None,
                 modo.fps if modo else None,
                 perfil, qualidade, time.time()),
            )
    except sqlite3.Error:
        pass
    finally:
        conexao.close()


def escolha(chave: str) -> tuple[ModoVideo | None, str, int | None]:
    """Devolve (modo, perfil, qualidade) lembrados. Tudo pode vir vazio."""
    if not chave:
        return None, "", None
    conexao = _conectar()
    if conexao is None:
        return None, "", None
    try:
        linha = conexao.execute(
            "SELECT codec, largura, altura, fps, perfil, qualidade"
            " FROM escolha WHERE chave = ?", (chave,)).fetchone()
    except sqlite3.Error:
        return None, "", None
    finally:
        conexao.close()

    if linha is None:
        return None, "", None
    codec, largura, altura, fps, perfil, qualidade = linha
    modo = (ModoVideo(codec, largura, altura, fps)
            if codec is not None and largura and altura and fps else None)
    return modo, perfil or "", qualidade


# --------------------------------------------------------------------------
# Resultado do teste de equipamento
# --------------------------------------------------------------------------

def lembrar_medicoes(chave: str, medicoes: dict) -> None:
    """Guarda o resultado de «Testar equipamento» para este dispositivo.

    Recebe o mesmo `dict[ModoVideo, Medicao]` que a interface ja usa. So os
    campos medidos sao gravados: veredito, `fps_real` e `uso` sao derivados e
    se recalculam sozinhos na leitura, entao guarda-los seria guardar a mesma
    verdade duas vezes e deixar as duas copias divergirem.
    """
    if not chave or not medicoes:
        return
    conexao = _conectar()
    if conexao is None:
        return
    agora = time.time()
    linhas = [
        (chave, modo.codec, modo.largura, modo.altura, modo.fps,
         m.quadros_reais, m.quadros_vazios, m.duracao, m.octetos, m.erro,
         m.ms_por_quadro, m.quadros_processados, agora)
        for modo, m in medicoes.items()
    ]
    try:
        with conexao:
            # Apaga antes de inserir: um teste novo substitui o anterior por
            # inteiro. Sem isso, um modo que sumiu da placa (porque a entrada
            # HDMI mudou de resolucao) ficaria para sempre com o veredito velho.
            conexao.execute("DELETE FROM medicao WHERE chave = ?", (chave,))
            conexao.executemany(
                "INSERT INTO medicao VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
    except sqlite3.Error:
        pass
    finally:
        conexao.close()


def medicoes(chave: str, classe_medicao) -> dict:
    """Le as medicoes guardadas, descartando as vencidas.

    `classe_medicao` e a `captura.Medicao`, recebida como argumento para este
    modulo nao importar o motor de captura so por causa de um construtor.
    """
    if not chave:
        return {}
    conexao = _conectar()
    if conexao is None:
        return {}
    limite = time.time() - VALIDADE_MEDICAO_S
    try:
        linhas = conexao.execute(
            "SELECT codec, largura, altura, fps, quadros_reais, quadros_vazios,"
            "       duracao, octetos, erro, ms_por_quadro, quadros_processados"
            " FROM medicao WHERE chave = ? AND medido_em >= ?",
            (chave, limite)).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conexao.close()

    resultado = {}
    for (codec, largura, altura, fps, reais, vazios,
         duracao, octetos, erro, ms, processados) in linhas:
        modo = ModoVideo(codec, largura, altura, fps)
        resultado[modo] = classe_medicao(
            modo=modo, quadros_reais=reais, quadros_vazios=vazios,
            duracao=duracao, octetos=octetos, erro=erro,
            ms_por_quadro=ms, quadros_processados=processados,
        )
    return resultado


# --------------------------------------------------------------------------
# Manutencao
# --------------------------------------------------------------------------

def esquecer(chave: str) -> None:
    """Apaga tudo o que se sabe sobre um dispositivo."""
    if not chave:
        return
    conexao = _conectar()
    if conexao is None:
        return
    try:
        with conexao:
            conexao.execute("DELETE FROM escolha WHERE chave = ?", (chave,))
            conexao.execute("DELETE FROM medicao WHERE chave = ?", (chave,))
    except sqlite3.Error:
        pass
    finally:
        conexao.close()


def esquecer_tudo() -> None:
    conexao = _conectar()
    if conexao is None:
        return
    try:
        with conexao:
            conexao.execute("DELETE FROM escolha")
            conexao.execute("DELETE FROM medicao")
    except sqlite3.Error:
        pass
    finally:
        conexao.close()


def resumo() -> list[tuple[str, int, float]]:
    """(chave, quantos modos medidos, quando foi visto) — para o `--memoria`."""
    conexao = _conectar()
    if conexao is None:
        return []
    try:
        return conexao.execute(
            "SELECT e.chave, (SELECT COUNT(*) FROM medicao m WHERE m.chave = e.chave),"
            "       e.visto_em FROM escolha e ORDER BY e.visto_em DESC").fetchall()
    except sqlite3.Error:
        return []
    finally:
        conexao.close()
