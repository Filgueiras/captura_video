"""Ponto de entrada.

    python -m capturador            abre a janela
    python -m capturador --listar   imprime os dispositivos e sai
    python -m capturador --memoria  mostra o que ficou lembrado de cada aparelho
"""

from __future__ import annotations

import argparse
import sys


def _listar() -> int:
    from . import dispositivos as disp

    resultado = disp.listar()
    if resultado.aviso:
        print(f"Aviso: {resultado.aviso}\n")

    if not resultado.video:
        print("Nenhum dispositivo de vídeo encontrado.")
    for dispositivo in resultado.video:
        print(f"\nVÍDEO  {dispositivo.nome}")
        print(f"       caminho: {dispositivo.caminho}")
        melhor = dispositivo.melhor_modo()
        for modo in dispositivo.modos:
            marca = " <- recomendado" if modo == melhor else ""
            print(f"       {modo.rotulo}{marca}")

    for dispositivo in resultado.audio:
        print(f"\nÁUDIO  {dispositivo.nome}")
        print(f"       caminho: {dispositivo.caminho}")
        print(f"       taxas: {dispositivo.taxas}   canais: {dispositivo.canais}")
    return 0


def _medir(duracao: float, tudo: bool) -> int:
    from . import dispositivos as disp
    from .captura import medir_modo

    achados = disp.listar()
    if not achados.video:
        print("Nenhuma placa de captura encontrada.")
        return 1

    placa = achados.video[0]
    modos = placa.modos if tudo else [m for m in placa.modos if m.comprimido]
    if not modos:
        modos = placa.modos

    print(f"Testando {placa.nome} — {len(modos)} modos × {duracao:g}s")
    print("Mede o que a placa entrega de fato e se esta máquina acompanha.\n")
    print(f"{'modo':>13}  {'anunc.':>6}  {'real':>6}  {'vazios':>6}  "
          f"{'Mbit/s':>7}  {'CPU/quadro':>10}  veredito")
    print("-" * 78)

    import time

    for indice, modo in enumerate(modos):
        if indice:
            # A placa leva um instante para ser liberada depois do fechamento;
            # abrir imediatamente devolve "I/O error" de vez em quando.
            time.sleep(0.5)
        m = medir_modo(placa, modo, duracao, decodificar=True)
        if m.erro:
            time.sleep(1.0)
            m = medir_modo(placa, modo, duracao, decodificar=True)
        if m.erro:
            print(f"{modo.largura}x{modo.altura:<7}  {m.erro}")
            continue
        proporcao = (
            "—" if m.honesto
            else f"{100 * m.quadros_vazios / (m.quadros_reais + m.quadros_vazios):.0f}%"
        )
        print(f"{modo.largura}x{modo.altura:<7}  {modo.fps:6.0f}  {m.fps_real:6.1f}  "
              f"{proporcao:>6}  {m.mbits:7.1f}  "
              f"{m.ms_por_quadro:5.1f}ms{m.uso*100:4.0f}%  {m.rotulo_veredito}")

    print("\n'vazios'      quadros sem imagem que a placa emite só para sustentar")
    print("              a taxa que declara; onde aparece, vale a coluna 'real'.")
    print("'CPU/quadro'  tempo para decodificar e reduzir um quadro, e quanto isso")
    print("              ocupa do intervalo disponível. Acima de 90% a prévia engasga.")
    return 0


def _memoria(esquecer: bool) -> int:
    import time

    from . import memoria
    from .captura import Medicao

    if esquecer:
        memoria.esquecer_tudo()
        print("Memória apagada. Na próxima abertura, tudo volta ao palpite automático.")
        return 0

    linhas = memoria.resumo()
    print(f"Banco: {memoria.caminho_banco()}\n")
    if not linhas:
        print("Nada lembrado ainda. A memória se enche sozinha conforme você usa:")
        print("cada escolha de modo é anotada, e «Testar equipamento» guarda o")
        print("resultado para não precisar medir de novo.")
        return 0

    for chave, quantos, visto_em in linhas:
        quando = time.strftime("%d/%m/%Y %H:%M", time.localtime(visto_em))
        modo, perfil, qualidade = memoria.escolha(chave)
        print(f"{chave}")
        print(f"       usado em: {quando}")
        print(f"       modo    : {modo.rotulo if modo else '—'}")
        print(f"       perfil  : {perfil or '—'}"
              + (f"   qualidade: {qualidade}" if qualidade is not None else ""))
        if quantos:
            print(f"       medidos : {quantos} modos")
            for m, med in sorted(memoria.medicoes(chave, Medicao).items(),
                                 key=lambda p: (-p[0].pixels, -p[0].fps)):
                print(f"                 {m.rotulo:44}  {med.rotulo_veredito}"
                      f"  ({med.fps_real:.0f} fps reais)")
        print()
    return 0


def _janela() -> int:
    from PySide6.QtWidgets import QApplication

    from .janela import JanelaPrincipal

    app = QApplication(sys.argv)
    app.setApplicationName("Captura USB")
    janela = JanelaPrincipal()
    janela.show()
    return app.exec()


def main() -> int:
    analisador = argparse.ArgumentParser(
        prog="capturador",
        description="Visualizador e gravador para placas de captura USB.",
    )
    analisador.add_argument(
        "--listar", action="store_true",
        help="lista os dispositivos e formatos disponíveis, sem abrir a janela",
    )
    analisador.add_argument(
        "--medir", action="store_true",
        help="mede a taxa de quadros real de cada modo (a anunciada costuma mentir)",
    )
    analisador.add_argument(
        "--segundos", type=float, default=4.0, metavar="N",
        help="duração de cada medição (padrão: 4)",
    )
    analisador.add_argument(
        "--tudo", action="store_true",
        help="com --medir, inclui também os formatos não comprimidos (bem mais lento)",
    )
    analisador.add_argument(
        "--memoria", action="store_true",
        help="mostra o modo, o perfil e as medições lembrados de cada aparelho",
    )
    analisador.add_argument(
        "--esquecer", action="store_true",
        help="com --memoria, apaga tudo o que foi lembrado",
    )
    argumentos = analisador.parse_args()

    if argumentos.listar:
        return _listar()
    if argumentos.medir:
        return _medir(argumentos.segundos, argumentos.tudo)
    if argumentos.memoria or argumentos.esquecer:
        return _memoria(argumentos.esquecer)
    return _janela()


if __name__ == "__main__":
    sys.exit(main())
