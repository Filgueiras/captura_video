# ADR-0018 — Empacotar com PyInstaller em modo pasta

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

O programa precisa chegar a alguém que não tem Python instalado e não deveria
precisar saber o que é `pip`. Rodar do código-fonte continua sendo o caminho de
desenvolvimento ([COMO_RODAR.md](../COMO_RODAR.md)), mas não é o que se entrega.

Duas decisões independentes: qual empacotador, e em que modo.

## Decisão

**PyInstaller**, em **modo pasta** (`onedir`), com a receita versionada em
[`capturador.spec`](../../capturador.spec) e um lançador
[`principal.py`](../../principal.py).

Resultado medido nesta máquina (Python 3.14.4, PyInstaller 6.20):

| | |
|---|---|
| Tempo de build | ~100 s |
| Tamanho de `dist/Captura USB/` | 227 MB, 327 arquivos |
| `Captura USB.exe` | 5 MB (o resto são as bibliotecas ao lado) |
| Memória com a janela aberta | ~92 MB |

Quatro escolhas dentro da receita merecem registro:

**Um lançador separado (`principal.py`).** O `capturador/__main__.py` usa imports
relativos (`from . import dispositivos`), que exigem que o módulo seja carregado
como parte do pacote. O PyInstaller carrega o script de entrada como `__main__`,
sem pacote — apontar a receita direto para `__main__.py` quebraria todos esses
imports. O lançador importa o pacote pelo nome e só então chama `main()`.

**`collect_dynamic_libs("av")`.** As DLLs do FFmpeg que o PyAV carrega ficam em
`av.libs`, **fora** do pacote Python. Sem recolhê-las explicitamente, o
executável abre normalmente e falha no primeiro `av.open()` — uma falha tardia e
confusa, porque a janela já apareceu.

**Sem UPX.** A compressão reduziria o tamanho e quebra a assinatura das DLLs do
Qt, além de disparar heurística de antivírus. Executável grande é um incômodo;
executável em quarentena é um bloqueio.

**Sem console (`console=False`).** É um aplicativo de janela; um terminal preto
atrás dele é ruído. O efeito colateral precisa ser conhecido: **erros de
inicialização não têm para onde ir**, e o modo `--listar`/`--medir` não imprime
nada no executável empacotado. Para depurar, troca-se para `console=True`
temporariamente.

**O `ffmpeg` de linha de comando NÃO é embutido.** Ele continua sendo
pré-requisito do sistema no Windows, porque é o que enumera os formatos que a
placa aceita ([0002](0002-ffmpeg-embutido-via-pyav.md)). Embutir os ~80 MB do
binário completo dobraria o tamanho para uma chamada que a maioria das máquinas
já tem instalada. Sem ele o programa abre e avisa, em vez de falhar.

## Consequências

- Distribui-se uma pasta: o usuário copia e dá duplo clique. Sem instalação, sem
  Python, sem `pip`.
- 227 MB é bastante para um programa que faz uma coisa. É Qt (~150 MB) mais
  FFmpeg (~60 MB), e nenhum dos dois é opcional
  ([0001](0001-aplicativo-de-janela-em-python-com-pyside6.md),
  [0002](0002-ffmpeg-embutido-via-pyav.md)). Para um programa que grava arquivos
  de 150 MB por **minuto**, não é o gargalo de ninguém.
- **O executável é específico da plataforma onde foi gerado.** Não há
  compilação cruzada: o `.exe` do Windows sai de uma máquina Windows, o binário
  Linux de uma máquina Linux.
- A pasta com as DLLs visíveis também satisfaz naturalmente a LGPL do Qt, que
  exige que as bibliotecas continuem substituíveis pelo usuário.
- `dist/` e `build/` são artefatos e não pertencem ao controle de versão.

## Alternativas consideradas

**PyInstaller em modo arquivo-único (`--onefile`).** Um `.exe` só, que é o que
todo mundo pede. Descartado pelo comportamento em execução: os 227 MB são
descompactados num diretório temporário **a cada abertura**. Em disco mecânico,
são vários segundos de tela vazia antes da janela aparecer, toda vez. Em disco
rápido é aceitável — quem preferir a troca precisa mudar duas linhas na receita,
documentadas em [COMO_GERAR_EXECUTAVEL.md](../COMO_GERAR_EXECUTAVEL.md).

**Nuitka.** Compila para C e gera binário menor e mais rápido a iniciar. Exige
toolchain de C na máquina de build e tem mais arestas com PySide6 e PyAV — mais
partes móveis para um ganho que não muda a experiência de uso.

**cx_Freeze.** Equivalente em resultado, com ecossistema menor de *hooks*. Os
hooks prontos de PySide6, PyAV e NumPy no PyInstaller são exatamente o que fez
este build funcionar sem ajuste manual de dependências.

**Instalador (MSI, Inno Setup, `.deb`).** Faz sentido quando houver distribuição
para terceiros de verdade. Hoje acrescentaria uma etapa de build para resolver
um problema que copiar uma pasta já resolve.
